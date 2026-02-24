from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import discord
from sqlalchemy import func, select, update

from StellariaPact.cogs.Voting.qo.CreateVoteSessionQo import CreateVoteSessionQo
from StellariaPact.dto import ProposalDto
from StellariaPact.models.Proposal import Proposal
from StellariaPact.models.ProposalIntake import ProposalIntake
from StellariaPact.models.UserVote import UserVote
from StellariaPact.models.VoteSession import VoteSession
from StellariaPact.share import DiscordUtils
from StellariaPact.share.enums import IntakeStatus, ProposalStatus, VoteDuration, VoteSessionType
from StellariaPact.share.StringUtils import StringUtils

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

        # 创建帖子
        pending_tag = self._resolve_forum_tag(
            forum=review_forum,
            raw_tag_id=self.bot.config.get("intake_tags", {}).get("pending_review"),
            tag_key="pending_review",
        )
        applied_tags = [pending_tag] if pending_tag else []

        title_prefix = self._get_title_prefix_for_status(IntakeStatus.PENDING_REVIEW)
        thread_name = (
            f"{title_prefix} {created_intake.title}" if title_prefix else created_intake.title
        )

        thread_with_message = await review_forum.create_thread(
            name=thread_name,
            content=content,
            view=IntakeReviewView(self.bot),
            applied_tags=applied_tags,
        )

        # 更新草案，关联帖子ID
        created_intake.review_thread_id = thread_with_message.thread.id
        await uow.intake.update_intake(created_intake)

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
        objection_publicity_channel_id = channels_config.get("objection_publicity")
        if not objection_publicity_channel_id:
            raise ValueError("公示频道未配置。")

        objection_publicity_channel = self.bot.get_channel(objection_publicity_channel_id)
        if not isinstance(objection_publicity_channel, discord.TextChannel):
            raise TypeError("公示频道类型不正确。")

        embed = IntakeEmbedBuilder.build_support_embed(intake, current_votes=0)
        assert intake.id is not None
        vote_msg = await objection_publicity_channel.send(
            embed=embed, view=IntakeSupportView(self.bot)
        )
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

        # 更新审核帖首楼内容并通知提案人
        await self._update_review_thread_message(intake, view=None, notify_proposer=True)

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
            f"> ### 提案原因\n{intake.reason}\n\n"
            f"> ### 议案动议\n{intake.motion}\n\n"
            f"> ### 执行方案\n{intake.implementation}\n\n"
            f"> ### 议案执行人\n{intake.executor}"
        )

        # 在讨论区创建帖子
        channels_config = self.bot.config.get("channels", {})
        discussion_forum_id = channels_config.get("discussion")
        if not discussion_forum_id:
            raise ValueError("议案讨论区未配置。")

        discussion_forum = self.bot.get_channel(discussion_forum_id)
        if not isinstance(discussion_forum, discord.ForumChannel):
            raise TypeError("议案讨论区类型不正确。")

        # 先创建讨论帖
        created_ts = int(datetime.utcnow().timestamp())
        discussion_content = (
            f"***提案人: <@{intake.author_id}>***\n\n"
            f"> ## 提案原因\n{intake.reason}\n\n"
            f"> ## 议案动议\n{intake.motion}\n\n"
            f"> ## 执行方案\n{intake.implementation}\n\n"
            f"> ## 议案执行人\n{intake.executor}\n\n"
            f"*讨论帖创建时间: <t:{created_ts}:f>*"
        )
        # 获取 discussion 标签
        tags_config = self.bot.config.get("tags", {})
        discussion_tag = self._resolve_forum_tag(
            forum=discussion_forum,
            raw_tag_id=tags_config.get("discussion"),
            tag_key="discussion",
        )
        applied_tags = [discussion_tag] if discussion_tag else []
        thread_with_message = await discussion_forum.create_thread(
            name=f"[讨论中] {intake.title}",
            content=discussion_content,
            applied_tags=applied_tags,
        )
        discussion_thread_id = thread_with_message.thread.id

        # 创建提案对象
        new_proposal = Proposal(
            discussion_thread_id=discussion_thread_id,
            proposer_id=intake.author_id,
            title=intake.title,
            content=proposal_content,
            status=ProposalStatus.DISCUSSION,
        )
        created_proposal = await uow.proposal.add_proposal(new_proposal)
        await uow.flush([created_proposal])

        # 同时更新 ProposalIntake 的 discussion_thread_id
        intake.discussion_thread_id = discussion_thread_id
        await uow.intake.update_intake(intake)

        # 派发事件，创建讨论帖投票面板与投票频道镜像
        proposal_dto = ProposalDto.model_validate(created_proposal)
        self.bot.dispatch(
            "vote_session_created",
            proposal_dto=proposal_dto,
            options=[],
            duration_hours=VoteDuration.PROPOSAL_DEFAULT,
            anonymous=True,
            realtime=True,
            notify=True,
            create_in_voting_channel=True,
            notify_creation_role=True,
            thread=thread_with_message.thread,
        )

        # 更新投票频道的面板为"成功"并移除按钮
        if not intake.voting_message_id:
            return created_proposal

        channels_config = self.bot.config.get("channels", {})
        channel = self.bot.get_channel(channels_config.get("objection_publicity"))
        if not isinstance(channel, discord.TextChannel):
            return created_proposal

        try:
            msg = await channel.fetch_message(intake.voting_message_id)
            success_embed = IntakeEmbedBuilder.build_support_result_embed(
                intake,
                success=True,
                thread_id=created_proposal.discussion_thread_id,
                current_votes=intake.required_votes,
            )
            await msg.edit(embed=success_embed, view=None)
        except Exception as e:
            logger.warning(f"更新成功面板失败: {e}")

        # 更新审核贴
        await self._update_review_thread_message(intake, view=None)

        # 更新审核帖标签
        await self._update_review_thread_tags(intake)

        return created_proposal

    async def handle_support_toggle(
        self, uow: "UnitOfWork", user_id: int, message_id: int
    ) -> tuple[str, int]:
        """
        处理用户对草案的支持切换逻辑。
        返回: (操作类型 "supported"|"withdrawn", 当前总票数)
        """
        # 通过消息ID获取草案（带锁）
        intake = await uow.intake.get_intake_by_voting_message_id(message_id, for_update=True)

        if not intake:
            raise ValueError("草案不存在。")

        assert intake.id is not None
        intake_id = intake.id

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

        # 更新公示频道的消息（票数变化）
        await self._update_support_message(intake, current_votes)

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

        # 查询与草案关联的投票会话
        vote_session_stmt = select(VoteSession).where(
            VoteSession.intake_id == intake_id,  # type: ignore
            VoteSession.session_type == VoteSessionType.INTAKE_SUPPORT,  # type: ignore
        )
        vote_session = (await uow.session.execute(vote_session_stmt)).scalar_one_or_none()

        current_votes = 0
        if vote_session:
            # 统计当前总票数
            count_stmt = select(func.count(UserVote.id)).where(  # type: ignore
                UserVote.session_id == vote_session.id
            )
            current_votes = (await uow.session.execute(count_stmt)).scalar_one() or 0

        # 更新草案状态为已拒绝（或新增一个 EXPIRED 状态，这里沿用 REJECTED）
        intake.status = IntakeStatus.REJECTED
        await uow.intake.update_intake(intake)

        # 更新审核贴消息
        await self._update_review_thread_message(
            intake, view=None, extra_note="草案因 3 天内支持票不足已自动关闭。"
        )

        # 更新审核帖标签
        await self._update_review_thread_tags(intake)

        # 更新公示频道的消息
        if intake.voting_message_id:
            channels_config = self.bot.config.get("channels", {})
            objection_publicity_channel_id = channels_config.get("objection_publicity")
            if objection_publicity_channel_id:
                channel = self.bot.get_channel(objection_publicity_channel_id)
                if isinstance(channel, discord.TextChannel):
                    try:
                        msg = await channel.fetch_message(intake.voting_message_id)
                        fail_embed = IntakeEmbedBuilder.build_support_result_embed(
                            intake, success=False, current_votes=current_votes
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

        await self._update_review_thread_message(intake, view=None, notify_proposer=True)

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

        await self._update_review_thread_message(intake, view=None, notify_proposer=True)

        # 更新审核帖标签
        await self._update_review_thread_tags(intake)

        return intake

    async def _update_support_message(self, intake: ProposalIntake, current_votes: int):
        """更新公示频道中的支持票面板（当前票数/通过票数）。"""
        if not intake.voting_message_id:
            return

        channels_config = self.bot.config.get("channels", {})
        channel = self.bot.get_channel(channels_config.get("objection_publicity"))
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            msg = await channel.fetch_message(intake.voting_message_id)
            embed = IntakeEmbedBuilder.build_support_embed(intake, current_votes=current_votes)
            assert intake.id is not None
            await msg.edit(embed=embed, view=IntakeSupportView(self.bot))
        except discord.NotFound:
            logger.warning(f"找不到支持票消息 {intake.voting_message_id}，跳过更新。")
        except discord.Forbidden:
            logger.error(f"没有权限编辑支持票消息 {intake.voting_message_id}。")
        except Exception as e:
            logger.warning(f"更新支持票面板失败 {intake.voting_message_id}: {e}")

    async def _update_review_thread_message(
        self,
        intake: ProposalIntake,
        view: discord.ui.View | None,
        extra_note: str | None = None,
        notify_proposer: bool = False,
    ):
        """更新审核帖子首楼内容，并在需要时通知提案人。"""
        if not intake.review_thread_id:
            logger.warning(f"草案 {intake.id} 缺少 review_thread_id，无法更新消息。")
            return

        thread = self.bot.get_channel(intake.review_thread_id)
        if not isinstance(thread, discord.Thread):
            logger.warning(f"草案 {intake.id} 的 review_thread_id 无效。")
            return

        try:
            msg = await thread.fetch_message(thread.id)

            submitted_ts = int(msg.created_at.timestamp())
            status_text = self._get_review_result_text(intake.status)
            status_emoji = {
                int(IntakeStatus.SUPPORT_COLLECTING): "✅",
                int(IntakeStatus.REJECTED): "❌",
                int(IntakeStatus.MODIFICATION_REQUIRED): "🟡",
                int(IntakeStatus.APPROVED): "🎉",
            }.get(int(intake.status), "ℹ️")

            lines = [
                f"👤 **提案人：** <@{intake.author_id}>",
                f"📅 **提交时间：** <t:{submitted_ts}:f>",
                f"🆔 **议案ID：** `{intake.id}`",
            ]

            if intake.reviewer_id and intake.reviewed_at:
                reviewed_ts = int(intake.reviewed_at.timestamp())
                lines.extend(
                    [
                        f"👨‍💼 **审核员：** <@{intake.reviewer_id}>",
                        f"📅 **审核时间：** <t:{reviewed_ts}:f>",
                    ]
                )

            lines.extend(
                [
                    "\n---\n",
                    f"\n🏷️ **议案标题**\n{intake.title}",
                    f"\n📝 **提案原因**\n{intake.reason}",
                    f"\n📋 **议案动议**\n{intake.motion}",
                    f"\n🔧 **执行方案**\n{intake.implementation}"
                    f"\n👨‍💼 **议案执行人**\n{intake.executor}",
                    "\n---\n",
                    f"{status_emoji} **状态：** {status_text}\n",
                    f"💬 **审核意见：** {intake.review_comment or '（无）'}",
                ]
            )

            if extra_note:
                lines.extend(["", f"ℹ️ {extra_note}"])

            await msg.edit(content="\n".join(lines), embed=None, view=view)

            if notify_proposer and intake.reviewer_id and intake.reviewed_at:
                reviewed_ts = int(intake.reviewed_at.timestamp())
                notify_lines = [
                    f"<@{intake.author_id}> 您的议案已被审核！",
                    "## 📋 审核记录",
                    f"👨‍💼 **审核员：** <@{intake.reviewer_id}>",
                    f"📅 **审核时间：** <t:{reviewed_ts}:f>",
                    f"{status_emoji} **审核结果：** {status_text}",
                    "",
                    "💬 **审核意见：**",
                    intake.review_comment or "（无）",
                    "---",
                    "📝 如有疑问，申请人可以联系审核员了解详细情况。",
                ]
                await thread.send("\n".join(notify_lines))

        except discord.NotFound:
            logger.error(f"无法在帖子 {thread.id} 中找到起始消息。")
        except discord.Forbidden:
            logger.error(f"没有权限编辑帖子 {thread.id} 中的消息。")

    def _get_review_result_text(self, status: int) -> str:
        """根据状态获取审核结果文本。"""
        result_map = {
            int(IntakeStatus.SUPPORT_COLLECTING): "审核通过",
            int(IntakeStatus.REJECTED): "审核拒绝",
            int(IntakeStatus.MODIFICATION_REQUIRED): "要求修改",
            int(IntakeStatus.APPROVED): "已发布",
        }
        return result_map.get(status, "状态更新")

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

    def _get_title_prefix_for_status(self, status: int) -> str | None:
        """根据状态获取审核帖标题前缀"""
        status_prefix_map = {
            int(IntakeStatus.PENDING_REVIEW): "[待审核]",
            int(IntakeStatus.SUPPORT_COLLECTING): "[已通过]",
            int(IntakeStatus.APPROVED): "[已发布]",
            int(IntakeStatus.REJECTED): "[未通过]",
            int(IntakeStatus.MODIFICATION_REQUIRED): "[需要修改]",
        }
        return status_prefix_map.get(status)

    def _resolve_forum_tag(
        self, forum: discord.ForumChannel, raw_tag_id: int | str | None, tag_key: str
    ) -> discord.ForumTag | None:
        """根据配置中的标签 ID 解析论坛标签。"""
        if raw_tag_id is None:
            return None

        try:
            tag_id = int(raw_tag_id)
        except (TypeError, ValueError):
            logger.warning(f"config.tags.{tag_key} 配置值无效: {raw_tag_id}")
            return None

        tag = next((item for item in forum.available_tags if item.id == tag_id), None)
        if tag is None:
            logger.warning(
                f"在论坛 {forum.id} 的可用标签中未找到 ID 为 {tag_id} 的 {tag_key} 标签。"
            )
            return None

        return tag

    async def _update_review_thread_tags(self, intake: ProposalIntake):
        """更新审核帖子的标签和标题前缀"""
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

        edit_payload = {}

        title_prefix = self._get_title_prefix_for_status(intake.status)
        if title_prefix:
            clean_title = StringUtils.clean_title(thread.name)
            new_title = f"{title_prefix} {clean_title}"
            if new_title != thread.name:
                edit_payload["name"] = new_title

        if new_tags is not None:
            edit_payload["applied_tags"] = new_tags

        if not edit_payload:
            return

        try:
            await thread.edit(**edit_payload)
        except discord.Forbidden:
            logger.error(f"没有权限编辑帖子 {thread.id} 的标签或标题。")
        except Exception as e:
            logger.error(f"更新帖子 {thread.id} 的标签或标题时出错: {e}")
