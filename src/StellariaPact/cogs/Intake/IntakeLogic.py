from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import discord
from sqlalchemy import func, select, update

from StellariaPact.cogs.Voting.qo.CreateVoteSessionQo import CreateVoteSessionQo
from StellariaPact.models.Proposal import Proposal
from StellariaPact.models.ProposalIntake import ProposalIntake
from StellariaPact.models.UserVote import UserVote
from StellariaPact.models.VoteSession import VoteSession
from StellariaPact.share import DiscordUtils
from StellariaPact.share.enums import IntakeStatus, ProposalStatus, VoteSessionType

from .views.IntakeEmbedBuilder import IntakeEmbedBuilder
from .views.IntakeReviewView import IntakeReviewView
from .views.IntakeSupportView import IntakeSupportView

if TYPE_CHECKING:
    from StellariaPact.cogs.Intake.dto.IntakeSubmissionDto import IntakeSubmissionDto
    from StellariaPact.share.StellariaPactBot import StellariaPactBot
    from StellariaPact.share.UnitOfWork import UnitOfWork

logger = logging.getLogger(__name__)


class IntakeLogic:
    """
    处理提案预审（Intake）核心业务逻辑的模块。
    """

    def __init__(self, bot: "StellariaPactBot"):
        self.bot = bot

    async def submit_intake(self, uow: "UnitOfWork", dto: "IntakeSubmissionDto") -> ProposalIntake:
        """
        处理新的草案提交。

        1. 在数据库中创建草案记录。
        2. 在指定的审核论坛中为此草案创建一个新的审核帖子。
        3. 在帖子中发送一条消息，附上包含"批准"、"拒绝"等操作的视图。
        4. 更新草案记录，关联新创建的审核帖子ID。
        """
        # 创建并保存草案实体
        intake = ProposalIntake(
            guild_id=dto.guild_id,
            author_id=dto.author_id,
            title=dto.title,
            reason=dto.reason,
            motion=dto.motion,
            implementation=dto.implementation,
            executor=dto.executor,
            status=IntakeStatus.PENDING_REVIEW,
        )
        created_intake = await uow.intake.create_intake(intake)
        await uow.flush([created_intake])

        # 在审核论坛创建帖子
        channels_config = self.bot.config.get("channels", {})
        review_forum_id = channels_config.get("intake_review")
        if not review_forum_id:
            logger.error("配置中未找到 'intake_review' 频道ID。")
            raise ValueError("审核频道未配置。")

        review_forum = self.bot.get_channel(review_forum_id)
        if not isinstance(review_forum, discord.ForumChannel):
            logger.error(f"ID为 {review_forum_id} 的频道不是论坛频道。")
            raise TypeError("审核频道类型不正确。")

        content = IntakeEmbedBuilder.build_review_content(created_intake)
        assert created_intake.id is not None
        thread_with_message = await review_forum.create_thread(
            name=f"{created_intake.title}",
            content=content,
            view=IntakeReviewView(self.bot),
        )

        # 更新草案，关联帖子ID
        created_intake.review_thread_id = thread_with_message.thread.id
        await uow.intake.update_intake(created_intake)

        # 更新审核帖标签
        await self._update_review_thread_tags(created_intake)

        # 在返回前将对象从会话中分离，避免会话关闭后的延迟加载问题
        uow.session.expunge(created_intake)

        return created_intake

    async def approve_intake(
        self, uow: "UnitOfWork", thread_id: int, reviewer_id: int, review_comment: str
    ) -> ProposalIntake:
        """
        通过审核帖子ID批准一个待审核的草案。

        1. 通过 thread_id 查询草案。
        2. 记录审核信息（审核人ID、审核时间、审核意见）。
        3. 将草案状态更新为"支持票收集中"。
        4. 在指定的投票频道发送一个消息，用于收集社区支持票。
        5. 为此草案创建一个"准入支持"类型的投票会话。
        """
        intake = await uow.intake.get_intake_by_review_thread_id(thread_id)
        if not intake:
            raise ValueError("未找到对应的草案。")
        if intake.status != IntakeStatus.PENDING_REVIEW:
            raise ValueError("草案状态不正确，无法批准。")
        if not intake.review_thread_id:
            raise ValueError("草案缺少审核帖子ID，无法继续。")

        # 记录审核信息
        intake.reviewer_id = reviewer_id
        intake.reviewed_at = datetime.utcnow()
        intake.review_comment = review_comment

        # 更新状态
        intake.status = IntakeStatus.SUPPORT_COLLECTING
        await uow.intake.update_intake(intake)

        # 在投票频道发送消息
        channels_config = self.bot.config.get("channels", {})
        voting_channel_id = channels_config.get("voting_channel")
        if not voting_channel_id:
            raise ValueError("投票频道未配置。")

        voting_channel = self.bot.get_channel(voting_channel_id)
        if not isinstance(voting_channel, discord.TextChannel):
            raise TypeError("投票频道类型不正确。")

        embed = IntakeEmbedBuilder.build_support_embed(intake)
        assert intake.id is not None
        vote_msg = await voting_channel.send(embed=embed, view=IntakeSupportView(intake.id))
        intake.voting_message_id = vote_msg.id
        await uow.intake.update_intake(intake)

        # 创建投票会话
        now = datetime.utcnow()
        vote_qo = CreateVoteSessionQo(
            guild_id=vote_msg.guild.id if vote_msg.guild else 0,
            thread_id=intake.review_thread_id,
            context_message_id=vote_msg.id,
            intake_id=intake.id,
            session_type=VoteSessionType.INTAKE_SUPPORT,
            end_time=now + timedelta(days=3),  # 记录结束时间
        )
        await uow.vote_session.create_vote_session(vote_qo)

        # 更新审核帖标签
        await self._update_review_thread_tags(intake)

        return intake

    async def handle_support_reached(self, uow: "UnitOfWork", intake: ProposalIntake) -> Proposal:
        """
        处理草案达到所需支持票数后的转正流程。

        1. 将草案数据同步到正式的提案（Proposal）表中。
        2. 在指定的议案讨论区为此新提案创建一个帖子。
        """
        if not intake:
            raise ValueError("草案不存在。")
        if intake.status != IntakeStatus.APPROVED:
            raise ValueError("草案状态不正确，无法立案。")

        # 同步数据到提案表
        proposal_content = (
            f"### 提案原因\n\n{intake.reason}"
            f"### 议案动议\n\n{intake.motion}"
            f"### 执行方案\n\n{intake.implementation}"
            f"### 议案执行人\n\n{intake.executor}"
        )

        new_proposal = Proposal(
            proposer_id=intake.author_id,
            title=intake.title,
            content=proposal_content,
            status=ProposalStatus.DISCUSSION,
        )
        created_proposal = await uow.proposal.add_proposal(new_proposal)
        await uow.flush([created_proposal])

        # 在讨论区创建帖子
        channels_config = self.bot.config.get("channels", {})
        discussion_forum_id = channels_config.get("discussion")
        if not discussion_forum_id:
            raise ValueError("议案讨论区未配置。")

        discussion_forum = self.bot.get_channel(discussion_forum_id)
        if not isinstance(discussion_forum, discord.ForumChannel):
            raise TypeError("议案讨论区类型不正确。")

        thread_with_message = await discussion_forum.create_thread(
            name=f"提案 #{created_proposal.id} - {created_proposal.title}",
            content=(
                f"该提案由草案 `#{intake.id}` 发起，现已进入正式讨论阶段。"
                f"\n\n---\n\n{proposal_content}"
            ),
        )
        created_proposal.discussion_thread_id = thread_with_message.thread.id
        await uow.proposal.update_proposal(created_proposal)

        # 同时更新 ProposalIntake 的 discussion_thread_id
        intake.discussion_thread_id = thread_with_message.thread.id
        await uow.intake.update_intake(intake)

        # 更新投票频道的面板为"成功"并移除按钮
        if not intake.voting_message_id:
            return created_proposal

        channels_config = self.bot.config.get("channels", {})
        channel = self.bot.get_channel(channels_config.get("voting_channel"))
        if not isinstance(channel, discord.TextChannel):
            return created_proposal

        try:
            msg = await channel.fetch_message(intake.voting_message_id)
            success_embed = IntakeEmbedBuilder.build_support_result_embed(
                intake, success=True, thread_id=created_proposal.discussion_thread_id
            )
            await msg.edit(embed=success_embed, view=None)
        except Exception as e:
            logger.warning(f"更新成功面板失败: {e}")

        # 更新审核贴
        await self._update_review_thread_message(intake, "草案已立案", view=None)

        # 更新审核帖标签
        await self._update_review_thread_tags(intake)

        return created_proposal

    async def handle_support_toggle(
        self, uow: "UnitOfWork", user_id: int, intake_id: int
    ) -> tuple[str, int]:
        """
        处理用户对草案的支持切换逻辑。
        返回: (操作类型 "supported"|"withdrawn", 当前总票数)
        """
        # 锁定并获取草案信息
        intake = await uow.intake.get_intake_by_id(intake_id, for_update=True)

        if not intake:
            raise ValueError("草案不存在。")

        # 如果状态已经不是"支持票收集中"，说明已经被别人抢先立案或已关闭
        if intake.status != IntakeStatus.SUPPORT_COLLECTING:
            # 重新计算一下票数并返回
            count_stmt = (
                select(func.count(UserVote.id))  # type: ignore
                .join(VoteSession, UserVote.session_id == VoteSession.id)  # type: ignore
                .where(VoteSession.intake_id == intake_id)  # type: ignore
                .where(VoteSession.session_type == VoteSessionType.INTAKE_SUPPORT)  # type: ignore
            )
            current_votes = (await uow.session.execute(count_stmt)).scalar_one()
            return "already_processed", current_votes or 0

        # 获取关联的投票会话
        stmt = (
            select(VoteSession)
            .where(VoteSession.intake_id == intake_id)  # type: ignore
            .where(VoteSession.session_type == VoteSessionType.INTAKE_SUPPORT)  # type: ignore
            .where(VoteSession.status == 1)  # type: ignore
        )
        result = await uow.session.execute(stmt)
        vote_session = result.scalars().one_or_none()
        if not vote_session:
            raise ValueError("找不到关联的投票会话。")

        # 检查用户是否已经投过票并处理投票
        user_vote_stmt = select(UserVote).where(
            UserVote.session_id == vote_session.id,
            UserVote.user_id == user_id,  # type: ignore
        )
        result = await uow.session.execute(user_vote_stmt)
        existing_vote = result.scalars().one_or_none()

        action = ""
        if existing_vote:
            await uow.session.delete(existing_vote)
            action = "withdrawn"
        else:
            new_vote = UserVote(
                session_id=vote_session.id,
                user_id=user_id,
                choice=1,
                choice_index=1,
            )
            uow.session.add(new_vote)
            action = "supported"

        await uow.flush()

        # 统计当前总票数
        count_stmt = select(func.count(UserVote.id)).where(  # type: ignore
            UserVote.session_id == vote_session.id  # type: ignore
        )
        current_votes = (await uow.session.execute(count_stmt)).scalar_one() or 0

        # 如果未达到立案阈值，直接返回
        if current_votes < intake.required_votes:
            return action, current_votes

        # 再次刷新以获取最新状态，防止在计票期间状态被外部更改
        await uow.session.refresh(intake)

        # 如果状态已经不是"支持票收集中"，说明已经被别人抢先处理
        if intake.status != IntakeStatus.SUPPORT_COLLECTING:
            action = "already_processed"
            return action, current_votes

        # 达到阈值且状态正确，执行立案流程
        intake.status = IntakeStatus.APPROVED
        await uow.intake.update_intake(intake)  # flush + refresh
        await self.handle_support_reached(uow, intake)
        action = "promoted"

        return action, current_votes

    async def close_expired_intake(self, uow: "UnitOfWork", intake_id: int):
        """
        处理因支持票不足而过期的草案。
        """
        intake = await uow.intake.get_intake_by_id(intake_id)
        if not intake:
            return
        if intake.status != IntakeStatus.SUPPORT_COLLECTING:
            return

        # 更新草案状态为已拒绝（或新增一个 EXPIRED 状态，这里沿用 REJECTED）
        intake.status = IntakeStatus.REJECTED
        await uow.intake.update_intake(intake)

        # 更新审核贴消息
        await self._update_review_thread_message(
            intake, "草案因 3 天内支持票不足已自动关闭。", view=None
        )

        # 更新审核帖标签
        await self._update_review_thread_tags(intake)

        # 更新投票频道的消息
        if intake.voting_message_id:
            channels_config = self.bot.config.get("channels", {})
            voting_channel_id = channels_config.get("voting_channel")
            if voting_channel_id:
                channel = self.bot.get_channel(voting_channel_id)
                if isinstance(channel, discord.TextChannel):
                    try:
                        msg = await channel.fetch_message(intake.voting_message_id)
                        fail_embed = IntakeEmbedBuilder.build_support_result_embed(
                            intake, success=False
                        )
                        await msg.edit(embed=fail_embed, view=None)
                    except Exception as e:
                        logger.warning(f"无法更新过期的投票消息 {intake.voting_message_id}: {e}")

        # 关闭关联的投票会话
        await uow.session.execute(
            update(VoteSession)
            .where(VoteSession.intake_id == intake_id)  # type: ignore
            .where(VoteSession.session_type == VoteSessionType.INTAKE_SUPPORT)  # type: ignore
            .values(status=0)
        )

    async def reject_intake(
        self, uow: "UnitOfWork", thread_id: int, reviewer_id: int, review_comment: str
    ) -> ProposalIntake:
        """
        通过审核帖子ID拒绝一个草案。

        1. 通过 thread_id 查询草案。
        2. 记录审核信息（审核人ID、审核时间、审核意见）。
        3. 更新草案状态为已拒绝。
        """
        intake = await uow.intake.get_intake_by_review_thread_id(thread_id)
        if not intake:
            raise ValueError("未找到对应的草案。")

        # 记录审核信息
        intake.reviewer_id = reviewer_id
        intake.reviewed_at = datetime.utcnow()
        intake.review_comment = review_comment

        # 更新状态
        intake.status = IntakeStatus.REJECTED
        await uow.intake.update_intake(intake)

        await self._update_review_thread_message(intake, "草案已被拒绝", view=None)

        # 更新审核帖标签
        await self._update_review_thread_tags(intake)

        return intake

    async def request_modification_intake(
        self, uow: "UnitOfWork", thread_id: int, reviewer_id: int, review_comment: str
    ) -> ProposalIntake:
        """
        通过审核帖子ID请求修改一个草案。

        1. 通过 thread_id 查询草案。
        2. 记录审核信息（审核人ID、审核时间、审核意见）。
        3. 更新草案状态为需要修改。
        """
        intake = await uow.intake.get_intake_by_review_thread_id(thread_id)
        if not intake:
            raise ValueError("未找到对应的草案。")

        # 记录审核信息
        intake.reviewer_id = reviewer_id
        intake.reviewed_at = datetime.utcnow()
        intake.review_comment = review_comment

        # 更新状态
        intake.status = IntakeStatus.MODIFICATION_REQUIRED
        await uow.intake.update_intake(intake)

        await self._update_review_thread_message(intake, "草案需要修改", view=None)

        # 更新审核帖标签
        await self._update_review_thread_tags(intake)

        return intake

    async def _update_review_thread_message(
        self, intake: ProposalIntake, message: str, view: discord.ui.View | None
    ):
        """更新审核帖子中的消息和视图。"""
        if not intake.review_thread_id:
            logger.warning(f"草案 {intake.id} 缺少 review_thread_id，无法更新消息。")
            return

        thread = self.bot.get_channel(intake.review_thread_id)
        if isinstance(thread, discord.Thread):
            try:
                msg = await thread.fetch_message(thread.id)
                embed = IntakeEmbedBuilder.build_review_embed(intake)
                await msg.edit(content=f"**状态更新**: {message}", embed=embed, view=view)
            except discord.NotFound:
                logger.error(f"无法在帖子 {thread.id} 中找到起始消息。")
            except discord.Forbidden:
                logger.error(f"没有权限编辑帖子 {thread.id} 中的消息。")

    def _get_tag_name_for_status(self, status: int) -> str | None:
        """根据状态获取对应的标签键名"""
        status_tag_map = {
            int(IntakeStatus.PENDING_REVIEW): "pending_review",
            int(IntakeStatus.SUPPORT_COLLECTING): "support_collecting",
            int(IntakeStatus.APPROVED): "approved",
            int(IntakeStatus.REJECTED): "rejected",
            int(IntakeStatus.MODIFICATION_REQUIRED): "modification_required",
        }
        return status_tag_map.get(status)

    async def _update_review_thread_tags(self, intake: ProposalIntake):
        """更新审核帖子的标签"""
        if not intake.review_thread_id:
            logger.warning(f"草案 {intake.id} 缺少 review_thread_id，无法更新标签。")
            return

        thread = self.bot.get_channel(intake.review_thread_id)
        if not isinstance(thread, discord.Thread):
            logger.warning(f"草案 {intake.id} 的 review_thread_id 无效。")
            return

        forum = thread.parent
        if not isinstance(forum, discord.ForumChannel):
            logger.warning(f"帖子 {thread.id} 的父频道不是论坛频道。")
            return

        target_tag_name = self._get_tag_name_for_status(intake.status)
        if not target_tag_name:
            logger.warning(f"草案 {intake.id} 的状态 {intake.status} 没有对应的标签。")
            return

        # 构建用于 intake_tags 的配置
        config = {
            "tags": self.bot.config.get("intake_tags", {}),
            "status_tag_keys": self.bot.config.get("intake_status_tag_keys", []),
        }

        new_tags = DiscordUtils.calculate_new_tags(
            current_tags=thread.applied_tags,
            forum_tags=forum.available_tags,
            config=config,
            target_tag_name=target_tag_name,
        )

        if new_tags is not None:
            try:
                await thread.edit(applied_tags=new_tags)
            except discord.Forbidden:
                logger.error(f"没有权限编辑帖子 {thread.id} 的标签。")
            except Exception as e:
                logger.error(f"更新帖子 {thread.id} 的标签时出错: {e}")
