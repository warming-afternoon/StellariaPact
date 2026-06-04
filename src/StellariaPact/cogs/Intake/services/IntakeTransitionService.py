from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord
from sqlalchemy import func, select

from StellariaPact.cogs.Intake.views.IntakeEmbedBuilder import IntakeEmbedBuilder
from StellariaPact.cogs.Moderation.qo import CreateConfirmationSessionQo
from StellariaPact.dto import ConfirmationSessionDto, ProposalDto
from StellariaPact.dto.ProposalIntakeDto import ProposalIntakeDto
from StellariaPact.models.Proposal import Proposal
from StellariaPact.models.UserVote import UserVote
from StellariaPact.models.VoteSession import VoteSession
from StellariaPact.share import DiscordUtils
from StellariaPact.share.ProposalContentFormatter import ProposalContentFormatter
from StellariaPact.share.UnitOfWork import UnitOfWork
from StellariaPact.share.enums import IntakeStatus, ProposalStatus, VoteDuration, VoteSessionType

if TYPE_CHECKING:
    from StellariaPact.cogs.Intake.services.IntakeDiscordHelper import IntakeDiscordHelper
    from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


class IntakeTransitionService:
    """负责达标后的立案、创建讨论帖、转段确认。"""

    def __init__(self, bot: "StellariaPactBot", discord_helper: "IntakeDiscordHelper"):
        self.bot = bot
        self.discord_helper = discord_helper

    # -------------------------
    # 达到发布票数后的立案流程
    # -------------------------

    async def voting_threshold_reached(self, intake_id: int) -> tuple[bool, int]:
        """达到发布票数。结束投票、修改草案状态并正式立案。"""
        latest_count = 0

        # 锁行确认是否达到阈值并更新状态
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

            if (
                intake.status != IntakeStatus.SUPPORT_COLLECTING
                or latest_count < intake.required_votes
            ):
                return False, latest_count

            intake.status = IntakeStatus.APPROVED
            await uow.intake.update_intake(intake)
            await uow.commit()

        # 执行立案
        await self.handle_support_reached(intake_id)

        return True, latest_count

    async def handle_support_reached(self, intake_id: int) -> ProposalDto | None:
        """处理草案达到所需支持票数后：创建锁定讨论帖并发起转段确认流程。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            intake = await uow.intake.get_intake_by_id(intake_id)
            if not intake:
                raise ValueError("草案不存在。")
            if intake.status != IntakeStatus.APPROVED:
                raise ValueError("草案状态不正确，无法立案。")
            intake_dto = ProposalIntakeDto.model_validate(intake)
            required_votes = intake.required_votes

        # 建立讨论帖并立即锁定
        channels_config = self.bot.config.get("channels", {})
        discussion_forum_id = channels_config.get("discussion")
        if not discussion_forum_id:
            raise ValueError("议案讨论区未配置。")

        discussion_forum = await DiscordUtils.fetch_channel(self.bot, discussion_forum_id)
        if not isinstance(discussion_forum, discord.ForumChannel):
            raise TypeError("议案讨论区类型不正确。")

        created_ts = int(datetime.now(timezone.utc).timestamp())
        discussion_body = ProposalContentFormatter.format_discussion_body(
            author_id=intake_dto.author_id,
            reason=intake_dto.reason,
            motion=intake_dto.motion,
            implementation=intake_dto.implementation,
            executor=intake_dto.executor,
            heading_level=2,
        )
        discussion_content = (
            f"{discussion_body}\n\n"
            f"*讨论帖创建时间: <t:{created_ts}:f>*\n\n"
            f"🔒 **此讨论帖暂为锁定状态，待提案委员确认后将解锁开放发言。**"
        )
        tags_config = self.bot.config.get("tags", {})
        discussion_tag = self.discord_helper.resolve_forum_tag(
            forum=discussion_forum,
            raw_tag_id=tags_config.get("discussion"),
            tag_key="discussion",
        )
        applied_tags = [discussion_tag] if discussion_tag else []
        try:
            thread_with_message = await discussion_forum.create_thread(
                name=f"[讨论中] {intake_dto.title}",
                content=discussion_content,
                applied_tags=applied_tags,
            )
        except discord.HTTPException as e:
            if e.code == 160006:
                logger.error(
                    f"创建讨论帖失败：讨论区 {discussion_forum_id} 活跃帖子已达上限。"
                    f"（Intake ID: {intake_id}, 标题: {intake_dto.title}）"
                )
                # 回滚草案状态到 SUPPORT_COLLECTING，避免数据库永久不一致
                async with UnitOfWork(self.bot.db_handler) as uow:
                    intake_to_rollback = await uow.intake.get_intake_by_id(
                        intake_id, for_update=True
                    )
                    if intake_to_rollback and intake_to_rollback.status == IntakeStatus.APPROVED:
                        intake_to_rollback.status = IntakeStatus.SUPPORT_COLLECTING
                        await uow.intake.update_intake(intake_to_rollback)
                        await uow.commit()
                        logger.info(
                            f"已将 Intake {intake_id} 状态从 APPROVED 回滚至 SUPPORT_COLLECTING，"
                            f"因讨论区活跃帖子已达上限。"
                        )
                raise ValueError(
                    "支持已记录，但创建讨论帖失败：讨论区活跃帖子已达上限。"
                    "请联系管理员归档旧帖后，再次点击支持按钮触发立案。"
                ) from e
            raise

        discussion_thread = thread_with_message.thread
        discussion_thread_id = discussion_thread.id

        await discussion_thread.edit(locked=True)
        await self.discord_helper.post_discussion_rules(discussion_thread)

        # 写入 Proposal 表并更新 Intake 草案
        proposal_content = ProposalContentFormatter.format_discussion_body(
            author_id=intake_dto.author_id,
            reason=intake_dto.reason,
            motion=intake_dto.motion,
            implementation=intake_dto.implementation,
            executor=intake_dto.executor,
            heading_level=3,
            include_header=False,
        )
        async with UnitOfWork(self.bot.db_handler) as uow:
            new_proposal = Proposal(
                discussion_thread_id=discussion_thread_id,
                proposer_id=intake_dto.author_id,
                title=intake_dto.title,
                content=proposal_content,
                status=ProposalStatus.DISCUSSION,
            )
            await uow.proposal.add_proposal(new_proposal)

            intake_to_update = await uow.intake.get_intake_by_id(intake_id, for_update=True)
            if not intake_to_update:
                raise ValueError("找不到草案。")
            intake_to_update.discussion_thread_id = discussion_thread_id
            await uow.intake.update_intake(intake_to_update)
            intake_dto = ProposalIntakeDto.model_validate(intake_to_update)
            await uow.commit()

        # 创建转段确认会话，直接发送到刚刚建立的锁定的讨论帖中
        session_dto = await self._create_intake_transition_session(intake_dto)
        if session_dto:
            await self.discord_helper.send_transition_confirmation_message(
                discussion_thread, session_dto, intake_dto.guild_id
            )

        # 更新公示消息
        if intake_dto.voting_message_id:
            pending_embed = IntakeEmbedBuilder.build_support_result_embed(
                intake_dto, success=True, current_votes=required_votes,
            )
            pending_embed.description = (
                "该提案已收集到足够的支持票，已开启讨论贴。\n"
                "⏳ 等待提案委员会确认后解锁讨论帖..."
            )
            channel = await DiscordUtils.fetch_channel(
                self.bot, channels_config.get("objection_publicity")
            )
            if isinstance(channel, discord.TextChannel):
                try:
                    msg = await channel.fetch_message(intake_dto.voting_message_id)
                    await msg.edit(embed=pending_embed, view=None)
                except Exception as e:
                    logger.warning(f"更新收集票面板失败: {e}")

        await self.discord_helper.update_review_thread_message(
            intake_dto, view=None,
            extra_note="🎉 支持票已达标！已建立锁定讨论帖，等待提案委员会确认解锁...",
        )
        await self.discord_helper.update_review_thread_tags(intake_dto)
        return None

    # -------------------------
    # 转段确认完成
    # -------------------------

    async def handle_intake_transition_confirmed(
        self, intake_id: int
    ) -> ProposalDto | None:
        """转段确认完成后：解锁讨论帖（新流程）或建立讨论帖（向后兼容）。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            intake = await uow.intake.get_intake_by_id(intake_id)
            if not intake:
                raise ValueError("草案不存在。")
            intake_dto = ProposalIntakeDto.model_validate(intake)
            required_votes = intake.required_votes

        # 新流程：讨论帖已在支持票达标立案时建立并锁定，仅需解锁并创建投票面板
        if intake_dto.discussion_thread_id:
            thread = await DiscordUtils.fetch_thread(self.bot, intake_dto.discussion_thread_id)
            if isinstance(thread, discord.Thread):
                await thread.edit(locked=False)

            # 获取 Proposal 记录并派发投票面板创建事件
            proposal_dto = None
            async with UnitOfWork(self.bot.db_handler) as uow_proposal:
                proposal_stmt = select(Proposal).where(
                    Proposal.discussion_thread_id == intake_dto.discussion_thread_id  # type: ignore
                )
                result = await uow_proposal.session.execute(proposal_stmt)
                proposal = result.scalars().one_or_none()
                if proposal:
                    proposal_dto = ProposalDto.model_validate(proposal)
                    self.bot.dispatch(
                        "vote_session_created",
                        proposal_dto=proposal_dto,
                        options=[],
                        duration_hours=VoteDuration.PROPOSAL_DEFAULT,
                        anonymous=True,
                        realtime=True,
                        notify=True,
                        create_in_voting_channel=True,
                        notify_creation_role=False,
                        thread=thread,
                        intake_id=intake_dto.id,
                    )

            # 更新公示消息状态为成功与解锁
            channels_config = self.bot.config.get("channels", {})
            if intake_dto.voting_message_id:
                success_embed = IntakeEmbedBuilder.build_support_result_embed(
                    intake_dto, success=True, thread_id=intake_dto.discussion_thread_id,
                    current_votes=required_votes,
                )
                channel = await DiscordUtils.fetch_channel(
                    self.bot, channels_config.get("objection_publicity")
                )
                if isinstance(channel, discord.TextChannel):
                    try:
                        msg = await channel.fetch_message(intake_dto.voting_message_id)
                        await msg.edit(embed=success_embed, view=None)
                    except Exception as e:
                        logger.warning(f"更新收集票面板失败: {e}")

            await self.discord_helper.update_review_thread_message(
                intake_dto, view=None,
                extra_note="✅ 讨论帖已解锁开放讨论！",
            )
            await self.discord_helper.update_review_thread_tags(intake_dto)
            return proposal_dto

        # 以下为向后兼容的旧流程：创建讨论帖
        channels_config = self.bot.config.get("channels", {})
        discussion_forum_id = channels_config.get("discussion")
        if not discussion_forum_id:
            raise ValueError("议案讨论区未配置。")

        discussion_forum = await DiscordUtils.fetch_channel(self.bot, discussion_forum_id)
        if not isinstance(discussion_forum, discord.ForumChannel):
            raise TypeError("议案讨论区类型不正确。")

        created_ts = int(datetime.now(timezone.utc).timestamp())
        discussion_body = ProposalContentFormatter.format_discussion_body(
            author_id=intake_dto.author_id,
            reason=intake_dto.reason,
            motion=intake_dto.motion,
            implementation=intake_dto.implementation,
            executor=intake_dto.executor,
            heading_level=2,
        )
        discussion_content = f"{discussion_body}\n\n*讨论帖创建时间: <t:{created_ts}:f>*"
        tags_config = self.bot.config.get("tags", {})
        discussion_tag = self.discord_helper.resolve_forum_tag(
            forum=discussion_forum,
            raw_tag_id=tags_config.get("discussion"),
            tag_key="discussion",
        )
        applied_tags = [discussion_tag] if discussion_tag else []
        try:
            thread_with_message = await discussion_forum.create_thread(
                name=f"[讨论中] {intake_dto.title}",
                content=discussion_content,
                applied_tags=applied_tags,
            )
        except discord.HTTPException as e:
            if e.code == 160006:
                logger.error(
                    f"创建讨论帖失败（转段确认向后兼容路径）："
                    f"讨论区 {discussion_forum_id} 活跃帖子已达上限。"
                    f"（Intake ID: {intake_id}, 标题: {intake_dto.title}）"
                )
                raise ValueError(
                    "创建讨论帖失败：讨论区活跃帖子已达上限。"
                    "请联系管理员归档旧帖后重新确认转段。"
                ) from e
            raise

        discussion_thread_id = thread_with_message.thread.id

        # 自动在讨论帖二楼发送参与准则
        await self.discord_helper.post_discussion_rules(thread_with_message.thread)

        # 写入 Proposal 表
        proposal_content = ProposalContentFormatter.format_discussion_body(
            author_id=intake_dto.author_id,
            reason=intake_dto.reason,
            motion=intake_dto.motion,
            implementation=intake_dto.implementation,
            executor=intake_dto.executor,
            heading_level=3,
            include_header=False,
        )
        async with UnitOfWork(self.bot.db_handler) as uow:
            new_proposal = Proposal(
                discussion_thread_id=discussion_thread_id,
                proposer_id=intake_dto.author_id,
                title=intake_dto.title,
                content=proposal_content,
                status=ProposalStatus.DISCUSSION,
            )
            created_proposal = await uow.proposal.add_proposal(new_proposal)

            intake_to_update = await uow.intake.get_intake_by_id(intake_id)
            if intake_to_update:
                intake_to_update.discussion_thread_id = discussion_thread_id
                await uow.intake.update_intake(intake_to_update)
                updated_intake_dto = ProposalIntakeDto.model_validate(intake_to_update)
            else:
                updated_intake_dto = intake_dto

            proposal_dto = ProposalDto.model_validate(created_proposal)
            await uow.commit()

        # 派发事件创建投票面板
        self.bot.dispatch(
            "vote_session_created",
            proposal_dto=proposal_dto,
            options=[],
            duration_hours=VoteDuration.PROPOSAL_DEFAULT,
            anonymous=True,
            realtime=True,
            notify=True,
            create_in_voting_channel=True,
            notify_creation_role=False,
            thread=thread_with_message.thread,
            intake_id=intake_id,
        )

        # 更新公示消息为成功状态
        voting_message_id = updated_intake_dto.voting_message_id
        if voting_message_id:
            success_embed = IntakeEmbedBuilder.build_support_result_embed(
                updated_intake_dto, success=True, thread_id=discussion_thread_id,
                current_votes=required_votes,
            )
            channel = await DiscordUtils.fetch_channel(
                self.bot, channels_config.get("objection_publicity")
            )
            if isinstance(channel, discord.TextChannel):
                try:
                    msg = await channel.fetch_message(voting_message_id)
                    await msg.edit(embed=success_embed, view=None)
                except Exception as e:
                    logger.warning(f"更新收集票面板失败: {e}")

        await self.discord_helper.update_review_thread_message(updated_intake_dto, view=None)
        await self.discord_helper.update_review_thread_tags(updated_intake_dto)
        return proposal_dto

    # -------------------------
    # 转段确认会话（私有方法）
    # -------------------------

    async def _create_intake_transition_session(
        self, intake_dto: ProposalIntakeDto
    ) -> ConfirmationSessionDto | None:
        """创建转段确认会话。"""
        assert intake_dto.id is not None
        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                qo = CreateConfirmationSessionQo(
                    context="intake_transition",
                    target_id=intake_dto.id,
                    message_id=0,
                    required_roles=["councilModerator", "executionAuditor"],
                    initiator_id=self.bot.user.id if self.bot.user else 0,
                    initiator_role_keys=[],
                )
                session = await uow.confirmation_session.create_confirmation_session(qo)
                session_dto = ConfirmationSessionDto.model_validate(session)
                await uow.commit()
                return session_dto
        except Exception as e:
            logger.error(f"创建转段确认会话失败: {e}", exc_info=True)
            return None
