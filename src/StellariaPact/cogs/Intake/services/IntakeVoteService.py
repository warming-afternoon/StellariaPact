from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from sqlalchemy import func, select, update

from StellariaPact.cogs.Intake.dto.SupportToggleDbResultDto import SupportToggleDbResultDto
from StellariaPact.cogs.Intake.views.IntakeEmbedBuilder import IntakeEmbedBuilder
from StellariaPact.dto.ProposalIntakeDto import ProposalIntakeDto
from StellariaPact.models.UserVote import UserVote
from StellariaPact.models.VoteSession import VoteSession
from StellariaPact.share import DiscordUtils
from StellariaPact.share.UnitOfWork import UnitOfWork
from StellariaPact.share.enums import IntakeStatus, VoteSessionType

if TYPE_CHECKING:
    from StellariaPact.cogs.Intake.services.IntakeDiscordHelper import IntakeDiscordHelper
    from StellariaPact.cogs.Intake.services.IntakeTransitionService import IntakeTransitionService
    from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


class IntakeVoteService:
    """负责支持票的收集、阈值判断、过期清理。"""

    def __init__(
        self,
        bot: "StellariaPactBot",
        discord_helper: "IntakeDiscordHelper",
        transition_service: "IntakeTransitionService",
    ):
        self.bot = bot
        self.discord_helper = discord_helper
        self.transition_service = transition_service

    # -------------------------
    # 支持票切换总入口
    # -------------------------

    async def process_support_toggle(self, interaction: discord.Interaction) -> tuple[str, int]:
        """支持票切换总入口"""
        assert interaction.message is not None
        message_id = interaction.message.id
        user_id = interaction.user.id

        # 处理用户对草案发布投票的投票状态切换
        async with UnitOfWork(self.bot.db_handler) as uow:
            result = await self.handle_support_toggle(uow, user_id, message_id)

        # 更新公示频道中的支持票收集面板
        if result.intake is not None:
            await self.discord_helper.update_support_message(result.intake, result.count)

        if not result.need_promote or result.intake_id is None:
            action, count = result.action, result.count
        else:
            # 如果达到票数，结束投票、修改草案状态并创建提案讨论帖
            promoted, latest_count = await self.transition_service.voting_threshold_reached(
                result.intake_id
            )
            action, count = (
                ("promoted", latest_count)
                if promoted
                else ("already_processed", latest_count)
            )

        if action == "supported":
            msg = f"✅ 收到支持！当前已收集到 **{count}** 张支持票"
        elif action == "withdrawn":
            msg = f"⎌ 已撤回支持。当前剩余 **{count}** 张支持票"
        elif action == "promoted":
            msg = f"🎉 收到支持！该草案已达到 **{count}** 票支持，已开启讨论贴"
        elif action == "already_processed":
            msg = f"👌 阶段已修改，当前总票数为 **{count}** 票"
        else:
            msg = "操作成功"

        await interaction.followup.send(msg, ephemeral=True)
        return action, count

    # -------------------------
    # 投票状态切换处理（DB 层）
    # -------------------------

    async def handle_support_toggle(
        self, uow: "UnitOfWork", user_id: int, message_id: int
    ) -> SupportToggleDbResultDto:
        """
        处理用户对草案发布投票的投票状态切换。
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

        # 达到阈值，触发立案流程
        return SupportToggleDbResultDto(
            action=action,
            count=current_votes,
            intake=intake_dto,
            need_promote=True,
            intake_id=intake_id,
        )

    # -------------------------
    # 过期草案关闭
    # -------------------------

    async def close_expired_intake(self, intake_id: int):
        """
        处理因支持票不足而过期的草案。
        """
        # 查询草案、投票会话并更新
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
                    intake_dto, success=False, current_votes=current_votes
                )

        # 更新审核帖首楼的审核信息
        await self.discord_helper.update_review_thread_message(
            intake_dto, view=None, extra_note="草案因 3 天内支持票不足已自动关闭。"
        )

        # 更新审核帖标签和标题
        await self.discord_helper.update_review_thread_tags(intake_dto)

        # 更新公示频道的消息
        if not voting_message_id or not fail_embed:
            return

        channels_config = self.bot.config.get("channels", {})
        objection_publicity_channel_id = channels_config.get("objection_publicity")
        if not objection_publicity_channel_id:
            return

        channel = await DiscordUtils.fetch_channel(self.bot, objection_publicity_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            msg = await channel.fetch_message(voting_message_id)
            await msg.edit(embed=fail_embed, view=None)
        except Exception as e:
            logger.warning(f"无法更新过期的投票消息 {voting_message_id}: {e}")
