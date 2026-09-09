from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import discord

from StellariaPact.cogs.Intake.views.IntakeEmbedBuilder import IntakeEmbedBuilder
from StellariaPact.cogs.Intake.views.IntakeReviewView import IntakeReviewView
from StellariaPact.cogs.Intake.views.IntakeSupportView import IntakeSupportView
from StellariaPact.dto.ProposalIntakeDto import ProposalIntakeDto
from StellariaPact.qo.vote_session import CreateVoteSessionQo
from StellariaPact.share import DiscordUtils, StringUtils
from StellariaPact.share.enums import IntakeStatus, LogOperationType, VoteSessionType
from StellariaPact.share.UnitOfWork import UnitOfWork

if TYPE_CHECKING:
    from StellariaPact.cogs.Intake.dto.IntakeSubmissionDto import IntakeSubmissionDto
    from StellariaPact.cogs.Intake.services.IntakeDiscordHelper import IntakeDiscordHelper
    from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


class IntakeReviewService:
    """负责管理员三人审核（批准/拒绝/要求修改）与作者修改。"""

    def __init__(self, bot: "StellariaPactBot", discord_helper: "IntakeDiscordHelper"):
        self.bot = bot
        self.discord_helper = discord_helper

    async def approve_intake(
        self,
        thread_id: int,
        reviewer_id: int,
        review_comment: str,
        operator_name: str = "",
        operator_display_name: str = "",
    ) -> tuple[ProposalIntakeDto, bool]:
        """记录三位不同管理的批准，只有第三票启动支持票收集。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            intake, count = await uow.intake.record_approval(
                thread_id, reviewer_id, review_comment,
            )
            intake_dto = ProposalIntakeDto.model_validate(intake)
            await uow.operation_log.log_operation(
                operator_id=reviewer_id,
                operator_name=operator_name,
                operator_display_name=operator_display_name,
                op_type=LogOperationType.INTAKE,
                action=("first_approve", "second_approve", "third_approve")[count - 1],
                target_type="intake",
                target_id=intake_dto.id,
                guild_id=intake_dto.guild_id,
                detail=f"审核进度: {count}/3；审核意见: {review_comment[:100]}",
            )
            await uow.commit()

        if count < 3:
            await self.discord_helper.update_review_thread_message(
                intake_dto, view=IntakeReviewView(self.bot, intake_dto),
            )
            return intake_dto, False

        await self._start_support_collection(intake_dto)
        return intake_dto, True

    async def _start_support_collection(self, intake_dto: ProposalIntakeDto) -> None:
        """三位管理确认后，创建支持票面板和投票会话。"""
        channels_config = self.bot.config.get("channels", {})

        # 在公示频道发送支持票面板
        objection_publicity_channel_id = channels_config.get("objection_publicity")
        if not objection_publicity_channel_id:
            raise ValueError("公示频道未配置。")

        objection_publicity_channel = await DiscordUtils.fetch_channel(
            self.bot, objection_publicity_channel_id
        )
        if not isinstance(objection_publicity_channel, discord.TextChannel):
            raise TypeError("公示频道类型不正确。")

        embed = IntakeEmbedBuilder.build_support_embed(intake_dto, current_votes=0)
        vote_msg = await objection_publicity_channel.send(
            embed=embed, view=IntakeSupportView(self.bot)
        )

        async with UnitOfWork(self.bot.db_handler) as uow:
            intake_to_update = await uow.intake.get_intake_by_id(intake_dto.id, for_update=True)
            if not intake_to_update:
                raise ValueError("在创建投票记录前找不到草案。")

            intake_to_update.voting_message_id = vote_msg.id
            await uow.intake.update_intake(intake_to_update)
            intake_dto = ProposalIntakeDto.model_validate(intake_to_update)

            if not intake_to_update.review_thread_id:
                raise ValueError("草案缺少审核帖子ID，无法创建投票会话。")

            now = datetime.now(timezone.utc)
            vote_qo = CreateVoteSessionQo(
                guild_id=vote_msg.guild.id if vote_msg.guild else 0,
                thread_id=intake_to_update.review_thread_id,
                context_message_id=vote_msg.id,
                intake_id=intake_to_update.id,
                session_type=VoteSessionType.INTAKE_SUPPORT,
                end_time=now + timedelta(days=3),
            )
            await uow.vote_session.create_vote_session(vote_qo)
            await uow.commit()

        # 更新审核帖首楼内容和标签
        await self.discord_helper.update_review_thread_message(
            intake_dto, view=None,
            extra_note="⏳ 已进入支持票收集阶段，等待支持票达标...",
            notify_proposer=True,
        )
        await self.discord_helper.update_review_thread_tags(intake_dto)

    # -------------------------
    # 草案审核 - 拒绝
    # -------------------------

    async def reject_intake(
        self,
        thread_id: int,
        reviewer_id: int,
        review_comment: str,
        operator_name: str = "",
        operator_display_name: str = "",
    ) -> ProposalIntakeDto:
        """草案审核 - 拒绝"""
        # 更新草案审核状态
        async with UnitOfWork(self.bot.db_handler) as uow:
            intake = await uow.intake.mark_reviewed(
                thread_id,
                reviewer_id,
                review_comment,
                IntakeStatus.REJECTED,
                expected_current_status=[
                    IntakeStatus.PENDING_REVIEW,
                    IntakeStatus.MODIFICATION_REQUIRED,
                ],
            )
            intake_dto = ProposalIntakeDto.model_validate(intake)

            # 写入操作日志
            await uow.operation_log.log_operation(
                operator_id=reviewer_id,
                operator_name=operator_name,
                operator_display_name=operator_display_name,
                op_type=LogOperationType.INTAKE,
                action="reject",
                target_type="intake",
                target_id=intake_dto.id,
                guild_id=intake_dto.guild_id,
                detail=f"审核意见: {review_comment[:100]}" if review_comment else None,
            )
            await uow.commit()

        # 修改审核帖首楼内容并发送审核公示
        view = IntakeReviewView(self.bot, intake_dto)
        await self.discord_helper.update_review_thread_message(
            intake_dto, view=view, notify_proposer=True
        )

        # 修改审核帖标题和标签
        await self.discord_helper.update_review_thread_tags(intake_dto)
        return intake_dto

    # -------------------------
    # 草案审核 - 要求修改
    # -------------------------

    async def request_modification_intake(
        self,
        thread_id: int,
        reviewer_id: int,
        review_comment: str,
        operator_name: str = "",
        operator_display_name: str = "",
    ) -> ProposalIntakeDto:
        """草案审核 - 需要修改"""
        # 更新草案审核状态
        async with UnitOfWork(self.bot.db_handler) as uow:
            intake = await uow.intake.mark_reviewed(
                thread_id,
                reviewer_id,
                review_comment,
                IntakeStatus.MODIFICATION_REQUIRED,
            )
            intake_dto = ProposalIntakeDto.model_validate(intake)

            # 写入操作日志
            await uow.operation_log.log_operation(
                operator_id=reviewer_id,
                operator_name=operator_name,
                operator_display_name=operator_display_name,
                op_type=LogOperationType.INTAKE,
                action="request_modification",
                target_type="intake",
                target_id=intake_dto.id,
                guild_id=intake_dto.guild_id,
                detail=f"审核意见: {review_comment[:100]}" if review_comment else None,
            )
            await uow.commit()

        # 修改审核帖首楼内容/标题/TAG 并发送修改公示
        view = IntakeReviewView(self.bot, intake_dto)
        await asyncio.gather(
            self.discord_helper.update_review_thread_message(
                intake_dto, view=view, notify_proposer=True
            ),
            self.discord_helper.update_review_thread_tags(intake_dto),
            return_exceptions=True,
        )
        return intake_dto

    # -------------------------
    # 提案人修改草案
    # -------------------------

    async def edit_intake(
        self,
        intake_id: int,
        dto: "IntakeSubmissionDto",
        operator_name: str = "",
        operator_display_name: str = "",
    ) -> ProposalIntakeDto:
        """提案人修改草案"""
        StringUtils.validate_proposal_title(dto.title)

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

            # 如果处于待审核状态被修改，重置全部管理员审核记录
            if intake.status == IntakeStatus.PENDING_REVIEW:
                intake.reviewer_id = None
                intake.reviewed_at = None
                intake.review_comment = None
                intake.reviewer_id_2 = None
                intake.reviewed_at_2 = None
                intake.review_comment_2 = None
                intake.reviewer_id_3 = None
                intake.reviewed_at_3 = None
                intake.review_comment_3 = None

            await uow.intake.update_intake(intake)

            intake_dto = ProposalIntakeDto.model_validate(intake)

            # 写入操作日志
            await uow.operation_log.log_operation(
                operator_id=dto.author_id,
                operator_name=operator_name,
                operator_display_name=operator_display_name,
                op_type=LogOperationType.INTAKE,
                action="author_edit",
                target_type="intake",
                target_id=intake_dto.id,
                guild_id=dto.guild_id,
                detail=f"修改后标题: {dto.title[:50]}",
            )
            await uow.commit()

        # 修改审核帖首楼内容并发送修改公示
        view = IntakeReviewView(self.bot, intake_dto)
        await self.discord_helper.update_review_thread_message(intake_dto, view=view)

        if intake_dto.review_thread_id:
            thread = await DiscordUtils.fetch_thread(self.bot, intake_dto.review_thread_id)
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

        # 修改审核帖标题和标签
        await self.discord_helper.update_review_thread_tags(intake_dto)
        return intake_dto
