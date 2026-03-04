from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import discord
from sqlalchemy import func, select, update

from StellariaPact.cogs.Intake.dto.SupportToggleDbResultDto import SupportToggleDbResultDto
from StellariaPact.cogs.Voting.qo.CreateVoteSessionQo import CreateVoteSessionQo
from StellariaPact.dto import ProposalDto
from StellariaPact.dto.ProposalIntakeDto import ProposalIntakeDto
from StellariaPact.models.Proposal import Proposal
from StellariaPact.models.ProposalIntake import ProposalIntake
from StellariaPact.models.UserVote import UserVote
from StellariaPact.models.VoteSession import VoteSession
from StellariaPact.share import DiscordUtils
from StellariaPact.share.enums import IntakeStatus, ProposalStatus, VoteDuration, VoteSessionType
from StellariaPact.share.UnitOfWork import UnitOfWork

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

    async def process_submit_intake(self, dto: "IntakeSubmissionDto") -> ProposalIntakeDto:
        """草案提交"""
        max_retries = 3
        retry_delay = 0.8
        # 创建草案
        created_intake: ProposalIntake | None = None
        intake_dto: ProposalIntakeDto | None = None
        for attempt in range(max_retries):
            try:
                async with UnitOfWork(self.bot.db_handler) as uow:
                    new_intake = ProposalIntake(
                        guild_id=dto.guild_id,
                        author_id=dto.author_id,
                        title=dto.title,
                        reason=dto.reason,
                        motion=dto.motion,
                        implementation=dto.implementation,
                        executor=dto.executor,
                        status=IntakeStatus.PENDING_REVIEW,
                        required_votes=2,
                    )
                    created = await uow.intake.create_intake(new_intake)
                    intake_dto = ProposalIntakeDto.model_validate(created)
                    created_intake = created
                    await uow.commit()
                    break
            except Exception as e:
                if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                    logger.warning(f"草案提交遇到数据库锁，正在重试 ({attempt + 1}/{max_retries})")
                    await asyncio.sleep(retry_delay)
                    continue
                raise

        if created_intake is None or intake_dto is None:
            raise RuntimeError("草案提交失败：未能创建草案记录。")

        # 创建审核帖
        channels_config = self.bot.config.get("channels", {})
        review_forum_id = channels_config.get("intake_review")
        if not review_forum_id:
            logger.error("配置中未找到 'intake_review' 频道ID。")
            raise ValueError("审核频道未配置。")

        review_forum = self.bot.get_channel(review_forum_id)
        if not isinstance(review_forum, discord.ForumChannel):
            logger.error(f"ID为 {review_forum_id} 的频道不是论坛频道。")
            raise TypeError("审核频道类型不正确。")

        content = IntakeEmbedBuilder.build_review_content(intake_dto)
        pending_tag = self._resolve_forum_tag(
            forum=review_forum,
            raw_tag_id=self.bot.config.get("intake_tags", {}).get("pending_review"),
            tag_key="pending_review",
        )
        applied_tags = [pending_tag] if pending_tag else []
        title_prefix = self._get_title_prefix_for_status(IntakeStatus.PENDING_REVIEW)
        thread_name = f"{title_prefix} {intake_dto.title}" if title_prefix else intake_dto.title

        thread_with_message = await review_forum.create_thread(
            name=thread_name,
            content=content,
            view=IntakeReviewView(self.bot, intake_dto),
            applied_tags=applied_tags,
        )

        # 回写 review_thread_id
        assert intake_dto.id is not None
        for attempt in range(max_retries):
            try:
                async with UnitOfWork(self.bot.db_handler) as uow:
                    intake = await uow.intake.get_intake_by_id(intake_dto.id, for_update=True)
                    if not intake:
                        raise ValueError(f"草案不存在，ID={intake_dto.id}")
                    intake.review_thread_id = thread_with_message.thread.id
                    await uow.intake.update_intake(intake)
                    intake_dto = ProposalIntakeDto.model_validate(intake)
                    await uow.commit()
                    return intake_dto
            except Exception as e:
                if "database is locked" in str(e).lower() and attempt < max_retries - 1:
                    logger.warning(f"回写审核帖ID遇到数据库锁，正在重试 ({attempt + 1}/{max_retries})")
                    await asyncio.sleep(retry_delay)
                    continue
                raise

        raise RuntimeError("草案提交失败：未能回写审核帖子ID。")


    async def approve_intake(
        self, thread_id: int, reviewer_id: int, review_comment: str
    ) -> ProposalIntakeDto:
        # 更新审核状态
        async with UnitOfWork(self.bot.db_handler) as uow:
            intake = await uow.intake.get_intake_by_review_thread_id(thread_id)
            if not intake:
                raise ValueError("未找到对应的草案。")
            if intake.status != IntakeStatus.PENDING_REVIEW:
                raise ValueError("草案状态不正确，无法批准。")
            if not intake.review_thread_id:
                raise ValueError("草案缺少审核帖子ID，无法继续。")

            intake.reviewer_id = reviewer_id
            intake.reviewed_at = datetime.now(timezone.utc)
            intake.review_comment = review_comment
            intake.status = IntakeStatus.SUPPORT_COLLECTING
            await uow.intake.update_intake(intake)

            # 序列化为 DTO
            intake_dto = ProposalIntakeDto.model_validate(intake)
            await uow.commit()

        # 在投票频道发送支持票面板
        channels_config = self.bot.config.get("channels", {})
        objection_publicity_channel_id = channels_config.get("objection_publicity")
        if not objection_publicity_channel_id:
            raise ValueError("公示频道未配置。")

        objection_publicity_channel = self.bot.get_channel(objection_publicity_channel_id)
        if not isinstance(objection_publicity_channel, discord.TextChannel):
            raise TypeError("公示频道类型不正确。")

        embed = IntakeEmbedBuilder.build_support_embed(intake_dto, current_votes=0)
        vote_msg = await objection_publicity_channel.send(
            embed=embed, view=IntakeSupportView(self.bot)
        )

        # 保存面板 Message ID 并创建投票会话记录
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 加锁重新获取并更新消息 ID
            intake = await uow.intake.get_intake_by_id(intake_dto.id, for_update=True)
            if not intake:
                raise ValueError("在创建投票会话时找不到草案。")

            intake.voting_message_id = vote_msg.id
            await uow.intake.update_intake(intake)

            now = datetime.now(timezone.utc)
            # 确保 review_thread_id 不为 None
            if not intake.review_thread_id:
                raise ValueError("草案缺少审核帖子ID，无法创建投票会话。")

            vote_qo = CreateVoteSessionQo(
                guild_id=vote_msg.guild.id if vote_msg.guild else 0,
                thread_id=intake.review_thread_id,
                context_message_id=vote_msg.id,
                intake_id=intake.id,
                session_type=VoteSessionType.INTAKE_SUPPORT,
                end_time=now + timedelta(days=3),
            )
            await uow.vote_session.create_vote_session(vote_qo)

            # 更新最终 DTO 用于后续更新帖子
            intake_dto = ProposalIntakeDto.model_validate(intake)
            await uow.commit()

        # 修改审核帖状态和标签
        await self._update_review_thread_message(intake_dto, view=None, notify_proposer=True)
        await self._update_review_thread_tags(intake_dto)

        return intake_dto

    async def handle_support_reached(self, intake_id: int) -> ProposalDto | None:
        """
        处理草案达到所需支持票数后的转正流程。
        """
        # 获取草案数据
        async with UnitOfWork(self.bot.db_handler) as uow:
            intake = await uow.intake.get_intake_by_id(intake_id)
            if not intake:
                raise ValueError("草案不存在。")
            if intake.status != IntakeStatus.APPROVED:
                raise ValueError("草案状态不正确，无法立案。")

            intake_dto = ProposalIntakeDto.model_validate(intake)
            required_votes = intake.required_votes

        # 同步数据到提案表的内容
        proposal_content = (
            f"> ### 提案原因\n{intake_dto.reason}\n\n"
            f"> ### 议案动议\n{intake_dto.motion}\n\n"
            f"> ### 执行方案\n{intake_dto.implementation}\n\n"
            f"> ### 议案执行人\n{intake_dto.executor}"
        )

        # 创建讨论帖
        channels_config = self.bot.config.get("channels", {})
        discussion_forum_id = channels_config.get("discussion")
        if not discussion_forum_id:
            raise ValueError("议案讨论区未配置。")

        discussion_forum = self.bot.get_channel(discussion_forum_id)
        if not isinstance(discussion_forum, discord.ForumChannel):
            raise TypeError("议案讨论区类型不正确。")

        created_ts = int(datetime.now(timezone.utc).timestamp())
        discussion_content = (
            f"***提案人: <@{intake_dto.author_id}>***\n\n"
            f"> ## 提案原因\n{intake_dto.reason}\n\n"
            f"> ## 议案动议\n{intake_dto.motion}\n\n"
            f"> ## 执行方案\n{intake_dto.implementation}\n\n"
            f"> ## 议案执行人\n{intake_dto.executor}\n\n"
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
            name=f"[讨论中] {intake_dto.title}",
            content=discussion_content,
            applied_tags=applied_tags,
        )
        discussion_thread_id = thread_with_message.thread.id

        # 将数据写入 Proposal 表，并更新 Intake
        async with UnitOfWork(self.bot.db_handler) as uow:
            new_proposal = Proposal(
                discussion_thread_id=discussion_thread_id,
                proposer_id=intake_dto.author_id,
                title=intake_dto.title,
                content=proposal_content,
                status=ProposalStatus.DISCUSSION,
            )
            created_proposal = await uow.proposal.add_proposal(new_proposal)

            # 重新获取 intake 更新以防并发版本冲突
            intake_to_update = await uow.intake.get_intake_by_id(intake_id)
            if intake_to_update:
                intake_to_update.discussion_thread_id = discussion_thread_id
                await uow.intake.update_intake(intake_to_update)

            proposal_dto = ProposalDto.model_validate(created_proposal)
            await uow.commit()

        # 派发事件
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

        # 更新旧有的公示消息和审核帖 UI
        async with UnitOfWork(self.bot.db_handler) as uow:
            final_intake = await uow.intake.get_intake_by_id(intake_id)
            if not final_intake:
                return proposal_dto
            final_intake_dto = ProposalIntakeDto.model_validate(final_intake)

            voting_message_id = final_intake.voting_message_id
            success_embed = None
            if voting_message_id:
                # 构建 Embed
                success_embed = IntakeEmbedBuilder.build_support_result_embed(
                    final_intake,
                    success=True,
                    thread_id=discussion_thread_id,
                    current_votes=required_votes,
                )

        if voting_message_id and success_embed:
            channel = self.bot.get_channel(channels_config.get("objection_publicity"))
            if isinstance(channel, discord.TextChannel):
                try:
                    msg = await channel.fetch_message(voting_message_id)
                    await msg.edit(embed=success_embed, view=None)
                except Exception as e:
                    logger.warning(f"更新成功面板失败: {e}")

        # 更新审核贴内容和标签
        await self._update_review_thread_message(final_intake_dto, view=None)
        await self._update_review_thread_tags(final_intake_dto)

        return proposal_dto

    async def process_support_toggle(self, interaction: discord.Interaction) -> tuple[str, int]:
        """支持票切换总入口：先完成纯 DB 事务，再执行 Discord API 与用户响应。"""
        assert interaction.message is not None
        message_id = interaction.message.id
        user_id = interaction.user.id

        async with UnitOfWork(self.bot.db_handler) as uow:
            result = await self.handle_support_toggle(uow, user_id, message_id)
            await uow.commit()

        if result.intake is not None:
            await self._update_support_message_by_dto(result.intake, result.count)

        if not result.need_promote or result.intake_id is None:
            action, count = result.action, result.count
        else:
            promoted, latest_count = await self._promote_if_threshold_reached(result.intake_id)
            action, count = (("promoted", latest_count) if promoted else ("already_processed", latest_count))

        if action == "supported":
            msg = f"✅ 收到支持！当前已收集到 **{count}** 张支持票"
        elif action == "withdrawn":
            msg = f"⎌ 已撤回支持。当前剩余 **{count}** 张支持票"
        elif action == "promoted":
            msg = f"🎉 收到支持！该草案已达到 **{count}** 票支持，已开启讨论贴"
        elif action == "already_processed":
            msg = f"👌 阶段已修改，当前总票数为 **{count}** 票"
        else:
            msg = "操作成功。"

        await interaction.followup.send(msg, ephemeral=True)
        return action, count

    async def handle_support_toggle(
        self, uow: "UnitOfWork", user_id: int, message_id: int
    ) -> SupportToggleDbResultDto:
        """
        处理用户对草案的支持切换逻辑（纯 DB 阶段）。
        返回结构化结果供提交后阶段使用。
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
            return SupportToggleDbResultDto(
                action="already_processed",
                count=current_votes or 0,
                intake=None,
                need_promote=False,
                intake_id=intake_id,
            )

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
        intake_dto = ProposalIntakeDto.model_validate(intake)

        # 如果未达到立案阈值，直接返回
        if current_votes < intake.required_votes:
            return SupportToggleDbResultDto(
                action=action,
                count=current_votes,
                intake=intake_dto,
                need_promote=False,
                intake_id=intake_id,
            )

        # 如果状态已经不是"支持票收集中"，说明已经被别人抢先处理
        if intake.status != IntakeStatus.SUPPORT_COLLECTING:
            return SupportToggleDbResultDto(
                action="already_processed",
                count=current_votes,
                intake=intake_dto,
                need_promote=False,
                intake_id=intake_id,
            )

        # 达到阈值，后续由提交后的二阶段逻辑推进立案
        return SupportToggleDbResultDto(
            action=action,
            count=current_votes,
            intake=intake_dto,
            need_promote=True,
            intake_id=intake_id,
        )

    async def _promote_if_threshold_reached(self, intake_id: int) -> tuple[bool, int]:
        """二阶段推进立案：先用短事务确认并更新状态，再在新事务中执行立案流程。"""
        latest_count = 0

        # 第一阶段：短事务，锁行确认是否达到阈值并更新状态
        async with UnitOfWork(self.bot.db_handler) as uow:
            intake = await uow.intake.get_intake_by_id(intake_id, for_update=True)
            if not intake:
                return False, 0

            vote_session_stmt = (
                select(VoteSession)
                .where(VoteSession.intake_id == intake_id)  # type: ignore
                .where(VoteSession.session_type == VoteSessionType.INTAKE_SUPPORT)  # type: ignore
                .where(VoteSession.status == 1)  # type: ignore
            )
            vote_session = (await uow.session.execute(vote_session_stmt)).scalars().one_or_none()
            if not vote_session:
                return False, 0

            count_stmt = select(func.count(UserVote.id)).where(  # type: ignore
                UserVote.session_id == vote_session.id  # type: ignore
            )
            latest_count = (await uow.session.execute(count_stmt)).scalar_one() or 0

            if intake.status != IntakeStatus.SUPPORT_COLLECTING or latest_count < intake.required_votes:
                return False, latest_count

            intake.status = IntakeStatus.APPROVED
            await uow.intake.update_intake(intake)
            await uow.commit()

        # 第二阶段：执行立案
        await self.handle_support_reached(intake_id)

        return True, latest_count

    async def close_expired_intake(self, intake_id: int):
        """
        处理因支持票不足而过期的草案。
        """
        # 第一阶段：短事务，查出并更新数据库
        async with UnitOfWork(self.bot.db_handler) as uow:
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

            # 更新草案状态为已拒绝
            intake.status = IntakeStatus.REJECTED
            await uow.intake.update_intake(intake)

            # 关闭关联的投票会话
            await uow.session.execute(
                update(VoteSession)
                .where(VoteSession.intake_id == intake_id)  # type: ignore
                .where(VoteSession.session_type == VoteSessionType.INTAKE_SUPPORT)  # type: ignore
                .values(status=0)
            )

            intake_dto = ProposalIntakeDto.model_validate(intake)
            voting_message_id = intake.voting_message_id
            fail_embed = None
            if voting_message_id:
                fail_embed = IntakeEmbedBuilder.build_support_result_embed(
                    intake, success=False, current_votes=current_votes
                )

            await uow.commit() # 释放锁

        # 第二阶段：调用 Discord API 更新通知面板
        await self._update_review_thread_message(
            intake_dto, view=None, extra_note="草案因 3 天内支持票不足已自动关闭。"
        )

        # 更新审核帖标签
        await self._update_review_thread_tags(intake_dto)

        # 更新公示频道的消息
        if voting_message_id and fail_embed:
            channels_config = self.bot.config.get("channels", {})
            objection_publicity_channel_id = channels_config.get("objection_publicity")
            if objection_publicity_channel_id:
                channel = self.bot.get_channel(objection_publicity_channel_id)
                if isinstance(channel, discord.TextChannel):
                    try:
                        msg = await channel.fetch_message(voting_message_id)
                        await msg.edit(embed=fail_embed, view=None)
                    except Exception as e:
                        logger.warning(f"无法更新过期的投票消息 {voting_message_id}: {e}")

    async def reject_intake(
        self, thread_id: int, reviewer_id: int, review_comment: str
    ) -> ProposalIntakeDto:
        # 更新审核状态
        async with UnitOfWork(self.bot.db_handler) as uow:
            intake = await uow.intake.get_intake_by_review_thread_id(thread_id)
            if not intake:
                raise ValueError("未找到对应的草案。")

            intake.reviewer_id = reviewer_id
            intake.reviewed_at = datetime.now(timezone.utc)
            intake.review_comment = review_comment
            intake.status = IntakeStatus.REJECTED
            await uow.intake.update_intake(intake)

            intake_dto = ProposalIntakeDto.model_validate(intake)
            await uow.commit()

        # 更新审核帖标签和首楼内容
        view = IntakeReviewView(self.bot, intake_dto)
        await self._update_review_thread_message(intake_dto, view=view, notify_proposer=True)
        await self._update_review_thread_tags(intake_dto)
        return intake_dto

    async def edit_intake(
        self, intake_id: int, dto: "IntakeSubmissionDto"
    ) -> ProposalIntakeDto:
        """
        处理提案人修改草案的逻辑。
        """
        # 更新提案内容
        async with UnitOfWork(self.bot.db_handler) as uow:
            intake = await uow.intake.get_intake_by_id(intake_id)
            if not intake:
                raise ValueError("未找到对应的草案。")

            intake.title = dto.title
            intake.reason = dto.reason
            intake.motion = dto.motion
            intake.implementation = dto.implementation
            intake.executor = dto.executor

            if intake.status == IntakeStatus.MODIFICATION_REQUIRED:
                intake.status = IntakeStatus.PENDING_REVIEW

            await uow.intake.update_intake(intake)

            intake_dto = ProposalIntakeDto.model_validate(intake)
            await uow.commit()

        # 更新审核帖首楼内容和重新渲染面板
        view = IntakeReviewView(self.bot, intake_dto)
        await self._update_review_thread_message(intake_dto, view=view)

        if intake_dto.review_thread_id:
            thread = self.bot.get_channel(intake_dto.review_thread_id)
            if isinstance(thread, discord.Thread):
                embed = discord.Embed(
                    title="📝 提案内容已更新",
                    description="提案人对草案内容进行了修改，请管理组重新审核。",
                    color=discord.Color.blue(),
                )
                embed.add_field(
                    name="修改时间",
                    value=f"<t:{int(datetime.now(timezone.utc).timestamp())}:f>",
                    inline=False,
                )
                embed.add_field(name="修改人", value=f"<@{intake_dto.author_id}>", inline=False)
                await thread.send(embed=embed)

        await self._update_review_thread_tags(intake_dto)
        return intake_dto

    async def request_modification_intake(
        self, thread_id: int, reviewer_id: int, review_comment: str
    ) -> ProposalIntakeDto:
        # DB 阶段
        async with UnitOfWork(self.bot.db_handler) as uow:
            intake = await uow.intake.get_intake_by_review_thread_id(thread_id)
            if not intake:
                raise ValueError("未找到对应的草案。")

            intake.reviewer_id = reviewer_id
            intake.reviewed_at = datetime.now(timezone.utc)
            intake.review_comment = review_comment
            intake.status = IntakeStatus.MODIFICATION_REQUIRED
            await uow.intake.update_intake(intake)

            intake_dto = ProposalIntakeDto.model_validate(intake)
            await uow.commit()

        # API 阶段
        view = IntakeReviewView(self.bot, intake_dto)
        await asyncio.gather(
            self._update_review_thread_message(intake_dto, view=view, notify_proposer=True),
            self._update_review_thread_tags(intake_dto),
            return_exceptions=True,
        )
        return intake_dto

    async def _update_support_message(self, intake: ProposalIntake, current_votes: int):
        """兼容入口：模型转 DTO 后更新公示频道中的支持票面板。"""
        await self._update_support_message_by_dto(ProposalIntakeDto.model_validate(intake), current_votes)

    async def _update_support_message_by_dto(self, intake: ProposalIntakeDto, current_votes: int):
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
            await msg.edit(embed=embed, view=IntakeSupportView(self.bot))
        except discord.NotFound:
            logger.warning(f"找不到支持票消息 {intake.voting_message_id}，跳过更新。")
        except discord.Forbidden:
            logger.error(f"没有权限编辑支持票消息 {intake.voting_message_id}。")
        except Exception as e:
            logger.warning(f"更新支持票面板失败 {intake.voting_message_id}: {e}")

    async def _update_review_thread_message(
        self,
        intake_dto: ProposalIntakeDto,
        view: discord.ui.View | None,
        extra_note: str | None = None,
        notify_proposer: bool = False,
    ):
        """更新审核帖子首楼内容，并在需要时通知提案人。"""
        if not intake_dto.review_thread_id:
            logger.warning(f"草案 {intake_dto.id} 缺少 review_thread_id，无法更新消息。")
            return

        thread = self.bot.get_channel(intake_dto.review_thread_id)
        if not isinstance(thread, discord.Thread):
            logger.warning(f"草案 {intake_dto.id} 的 review_thread_id 无效。")
            return

        try:
            msg = await thread.fetch_message(thread.id)

            submitted_ts = int(msg.created_at.timestamp())
            status_text = self._get_review_result_text(intake_dto.status)
            status_emoji = {
                int(IntakeStatus.SUPPORT_COLLECTING): "✅",
                int(IntakeStatus.REJECTED): "❌",
                int(IntakeStatus.MODIFICATION_REQUIRED): "🟡",
                int(IntakeStatus.APPROVED): "🎉",
            }.get(int(intake_dto.status), "ℹ️")

            lines = [
                f"👤 **提案人：** <@{intake_dto.author_id}>",
                f"📅 **提交时间：** <t:{submitted_ts}:f>",
                f"🆔 **议案ID：** `{intake_dto.id}`",
            ]

            if intake_dto.reviewer_id and intake_dto.reviewed_at:
                reviewed_ts = int(intake_dto.reviewed_at.timestamp())
                lines.extend(
                    [
                        f"👨‍💼 **审核员：** <@{intake_dto.reviewer_id}>",
                        f"📅 **审核时间：** <t:{reviewed_ts}:f>",
                    ]
                )

            lines.extend(
                [
                    "\n---\n",
                    f"\n🏷️ **议案标题**\n{intake_dto.title}",
                    f"\n📝 **提案原因**\n{intake_dto.reason}",
                    f"\n📋 **议案动议**\n{intake_dto.motion}",
                    f"\n🔧 **执行方案**\n{intake_dto.implementation}"
                    f"\n\n👨‍💼 **议案执行人**\n{intake_dto.executor}",
                    "\n---\n",
                    f"{status_emoji} **状态：** {status_text}\n",
                    f"💬 **审核意见：** {intake_dto.review_comment or '（无）'}",
                ]
            )

            if extra_note:
                lines.extend(["", f"ℹ️ {extra_note}"])

            await msg.edit(content="\n".join(lines), embed=None, view=view)

            if notify_proposer and intake_dto.reviewer_id and intake_dto.reviewed_at:
                reviewed_ts = int(intake_dto.reviewed_at.timestamp())
                notify_lines = [
                    f"<@{intake_dto.author_id}> 您的议案已被审核！",
                    "## 📋 审核记录",
                    f"👨‍💼 **审核员：** <@{intake_dto.reviewer_id}>",
                    f"📅 **审核时间：** <t:{reviewed_ts}:f>",
                    f"{status_emoji} **审核结果：** {status_text}",
                    "",
                    "💬 **审核意见：**",
                    intake_dto.review_comment or "（无）",
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
        # 强制转换为 int 确保匹配
        return status_tag_map.get(int(status))

    def _get_title_prefix_for_status(self, status: int) -> str | None:
        """根据状态获取审核帖标题前缀"""
        status_prefix_map = {
            int(IntakeStatus.PENDING_REVIEW): "[待审核]",
            int(IntakeStatus.SUPPORT_COLLECTING): "[已通过]",
            int(IntakeStatus.APPROVED): "[已发布]",
            int(IntakeStatus.REJECTED): "[未通过]",
            int(IntakeStatus.MODIFICATION_REQUIRED): "[需要修改]",
        }
        # 强制转换为 int 确保匹配
        return status_prefix_map.get(int(status))

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

    async def _update_review_thread_tags(self, intake_dto: ProposalIntakeDto):
        """更新审核帖子的标签和标题前缀"""
        if not intake_dto.review_thread_id:
            logger.warning(f"草案 {intake_dto.id} 缺少 review_thread_id，无法更新标签。")
            return

        thread = await DiscordUtils.fetch_thread(self.bot, intake_dto.review_thread_id)
        if not thread:
            logger.warning(f"草案 {intake_dto.id} 的 review_thread_id 无效。")
            return

        forum = thread.parent
        if not isinstance(forum, discord.ForumChannel):
            logger.warning(f"帖子 {thread.id} 的父频道不是论坛频道。")
            return

        target_tag_name = self._get_tag_name_for_status(intake_dto.status)
        if not target_tag_name:
            logger.warning(f"草案 {intake_dto.id} 的状态 {intake_dto.status} 没有对应的标签。")
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

        title_prefix = self._get_title_prefix_for_status(intake_dto.status)
        new_title = f"{title_prefix} {intake_dto.title}" if title_prefix else intake_dto.title

        # 确保标题长度不超过 Discord 限制（100 个字符）
        if len(new_title) > 100:
            new_title = new_title[:97] + "..."

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
