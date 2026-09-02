import json
import logging
from datetime import datetime, timedelta, timezone

import discord

from StellariaPact.cogs.Voting.VotingLogic import VotingLogic
from StellariaPact.dto.UserActivityDto import UserActivityDto
from StellariaPact.dto.vote_session import VoteDetailDto
from StellariaPact.share import StellariaPactBot, UnitOfWork
from StellariaPact.share.enums import LogOperationType, PunishmentType

from ..dto import ThreadPunishmentResult
from ..views.PunishmentEmbedBuilder import PunishmentEmbedBuilder

logger = logging.getLogger(__name__)


class PunishmentLogic:
    def __init__(self, bot: StellariaPactBot):
        self.bot = bot

    async def apply_thread_punishment(
        self,
        *,
        guild_id: int,
        thread_id: int,
        target_user_id: int,
        moderator_id: int,
        reason: str,
        source_message_url: str | None,
        voting_allowed: bool,
        mute_end_time: datetime | None,
    ) -> ThreadPunishmentResult:
        """
        应用帖子内处罚，并在剥夺投票资格时清除该用户仍在进行中的投票。

        资格状态、处罚记录和活动票删除在同一事务内完成。返回处罚记录 ID
        以及需要同步刷新的投票详情。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            await uow.user_activity.update_user_validation_status(
                user_id=target_user_id,
                thread_id=thread_id,
                is_valid=voting_allowed,
                mute_end_time=mute_end_time,
            )
            record = await uow.punishment_record.create_record(
                guild_id=guild_id,
                thread_id=thread_id,
                target_user_id=target_user_id,
                moderator_id=moderator_id,
                reason=reason,
                source_message_url=source_message_url,
                voting_allowed=voting_allowed,
                mute_end_time=mute_end_time,
            )
            if record.id is None:
                raise RuntimeError("帖子内处罚记录缺少数据库主键。")
            record_id = record.id

            vote_details_to_update: list[VoteDetailDto] = []
            if not voting_allowed:
                vote_details_to_update = await VotingLogic.remove_active_user_votes_in_thread(
                    uow=uow,
                    user_id=target_user_id,
                    thread_id=thread_id,
                )

            await uow.commit()
            return ThreadPunishmentResult(
                punishment_record_id=record_id,
                vote_details_to_update=vote_details_to_update,
            )

    async def set_thread_punishment_publicity_message(
        self,
        punishment_record_id: int,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int,
    ) -> None:
        """在独立事务中保存帖子内处罚正式公示消息的位置。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            await uow.punishment_record.set_publicity_message(
                punishment_record_id,
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=message_id,
            )
            await uow.commit()

    async def apply_permanent_restriction(
        self,
        *,
        punishment_type: PunishmentType,
        target_user_id: int,
        moderator_id: int,
        origin_guild_id: int,
        origin_channel_id: int,
        reason: str,
        evidence_url: str | None,
        evidence_filename: str | None,
        moderator_name: str,
        moderator_display_name: str,
    ) -> int:
        """按分类永久剥夺用户的提案权限。"""
        action = {
            PunishmentType.PERMANENT_VOTING: "apply_permanent_voting",
            PunishmentType.PERMANENT_OBJECTION_CREATION: "apply_permanent_objection_creation",
        }.get(punishment_type)
        if action is None:
            raise ValueError("不支持的永久权限处罚分类。")
        async with UnitOfWork(self.bot.db_handler) as uow:
            punishment = await uow.global_proposal_punishment.create_punishment(
                target_user_id=target_user_id,
                moderator_id=moderator_id,
                origin_guild_id=origin_guild_id,
                origin_channel_id=origin_channel_id,
                punishment_type=punishment_type,
                reason=reason,
                evidence_url=evidence_url,
                evidence_filename=evidence_filename,
            )
            punishment_id = self._require_punishment_id(punishment.id)
            await self._log_global_punishment_operation(
                uow=uow,
                punishment_id=punishment_id,
                target_user_id=target_user_id,
                moderator_id=moderator_id,
                moderator_name=moderator_name,
                moderator_display_name=moderator_display_name,
                guild_id=origin_guild_id,
                action=action,
                punishment_type=punishment_type,
                reason=reason,
                origin_channel_id=origin_channel_id,
            )
            await uow.commit()
            return punishment_id

    async def lift_permanent_restriction(
        self,
        *,
        punishment_type: PunishmentType,
        target_user_id: int,
        lifted_by_id: int,
        lift_reason: str,
        moderator_name: str,
        moderator_display_name: str,
        guild_id: int,
        channel_id: int,
    ) -> tuple[int, datetime]:
        """按分类解除用户的永久提案权限限制。"""
        action = {
            PunishmentType.PERMANENT_VOTING: "lift_permanent_voting",
            PunishmentType.PERMANENT_OBJECTION_CREATION: "lift_permanent_objection_creation",
        }.get(punishment_type)
        if action is None:
            raise ValueError("不支持的永久权限处罚分类。")
        async with UnitOfWork(self.bot.db_handler) as uow:
            restriction = await uow.global_proposal_punishment.lift_punishment(
                target_user_id=target_user_id,
                punishment_type=punishment_type,
                lifted_by_id=lifted_by_id,
                lift_reason=lift_reason,
            )
            punishment_id = self._require_punishment_id(restriction.id)
            original_created_at = restriction.created_at
            await self._log_global_punishment_operation(
                uow=uow,
                punishment_id=punishment_id,
                target_user_id=target_user_id,
                moderator_id=lifted_by_id,
                moderator_name=moderator_name,
                moderator_display_name=moderator_display_name,
                guild_id=guild_id,
                action=action,
                punishment_type=punishment_type,
                reason=lift_reason,
                origin_channel_id=channel_id,
            )
            await uow.commit()
            return punishment_id, original_created_at

    async def apply_global_voting_restriction(self, **kwargs) -> int:
        """兼容旧调用：永久剥夺投票资格。"""
        return await self.apply_permanent_restriction(
            punishment_type=PunishmentType.PERMANENT_VOTING,
            **kwargs,
        )

    async def lift_global_voting_restriction(self, **kwargs) -> tuple[int, datetime]:
        """兼容旧调用：解除永久投票资格限制。"""
        return await self.lift_permanent_restriction(
            punishment_type=PunishmentType.PERMANENT_VOTING,
            **kwargs,
        )

    async def apply_proposal_violation_punishment(
        self,
        *,
        target_user_id: int,
        moderator_id: int,
        origin_guild_id: int,
        origin_channel_id: int,
        days: int,
        reason: str,
        evidence_url: str | None,
        evidence_filename: str | None,
        moderator_name: str,
        moderator_display_name: str,
    ) -> tuple[int, datetime]:
        """创建用户的机器人全局提案违规处罚。"""
        if not 1 <= days <= 30:
            raise ValueError("提案违规处罚天数必须在 1 至 30 天之间。")
        expires_at = datetime.now(timezone.utc) + timedelta(days=days)
        async with UnitOfWork(self.bot.db_handler) as uow:
            punishment = await uow.global_proposal_punishment.create_punishment(
                target_user_id=target_user_id,
                moderator_id=moderator_id,
                origin_guild_id=origin_guild_id,
                origin_channel_id=origin_channel_id,
                punishment_type=PunishmentType.PROPOSAL_VIOLATION,
                reason=reason,
                expires_at=expires_at,
                evidence_url=evidence_url,
                evidence_filename=evidence_filename,
            )
            punishment_id = self._require_punishment_id(punishment.id)
            await self._log_global_punishment_operation(
                uow=uow,
                punishment_id=punishment_id,
                target_user_id=target_user_id,
                moderator_id=moderator_id,
                moderator_name=moderator_name,
                moderator_display_name=moderator_display_name,
                guild_id=origin_guild_id,
                action="apply_proposal_violation",
                punishment_type=PunishmentType.PROPOSAL_VIOLATION,
                reason=reason,
                origin_channel_id=origin_channel_id,
                expires_at=expires_at,
            )
            await uow.commit()
            return punishment_id, expires_at

    async def lift_proposal_violation_punishment(
        self,
        *,
        target_user_id: int,
        lifted_by_id: int,
        lift_reason: str,
        moderator_name: str,
        moderator_display_name: str,
        guild_id: int,
        channel_id: int,
    ) -> tuple[int, datetime, datetime]:
        """提前解除用户的机器人全局提案违规处罚。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            punishment = await uow.global_proposal_punishment.lift_punishment(
                target_user_id=target_user_id,
                punishment_type=PunishmentType.PROPOSAL_VIOLATION,
                lifted_by_id=lifted_by_id,
                lift_reason=lift_reason,
            )
            if punishment.expires_at is None:
                raise ValueError("提案违规处罚缺少截止时间。")
            punishment_id = self._require_punishment_id(punishment.id)
            result = (punishment_id, punishment.created_at, punishment.expires_at)
            await self._log_global_punishment_operation(
                uow=uow,
                punishment_id=punishment_id,
                target_user_id=target_user_id,
                moderator_id=lifted_by_id,
                moderator_name=moderator_name,
                moderator_display_name=moderator_display_name,
                guild_id=guild_id,
                action="lift_proposal_violation",
                punishment_type=PunishmentType.PROPOSAL_VIOLATION,
                reason=lift_reason,
                origin_channel_id=channel_id,
            )
            await uow.commit()
            return result

    async def set_punishment_message_id(
        self,
        punishment_id: int,
        message_id: int,
    ) -> None:
        """在独立事务中保存原始处罚公示消息 ID。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            await uow.global_proposal_punishment.set_punishment_message_id(
                punishment_id,
                message_id,
            )
            await uow.commit()

    async def set_resolution_message(
        self,
        punishment_id: int,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int,
    ) -> None:
        """在独立事务中保存解除公示消息的完整位置。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            await uow.global_proposal_punishment.set_resolution_message(
                punishment_id,
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=message_id,
            )
            await uow.commit()

    @staticmethod
    def _require_punishment_id(punishment_id: int | None) -> int:
        """确保已刷新处罚记录取得数据库主键。"""
        if punishment_id is None:
            raise RuntimeError("全局提案处罚记录缺少数据库主键。")
        return punishment_id

    @staticmethod
    async def _log_global_punishment_operation(
        *,
        uow: UnitOfWork,
        punishment_id: int,
        target_user_id: int,
        moderator_id: int,
        moderator_name: str,
        moderator_display_name: str,
        guild_id: int,
        action: str,
        punishment_type: PunishmentType,
        reason: str,
        origin_channel_id: int | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        """在处罚事务内写入不包含临时附件链接的结构化审计记录。"""
        detail = {
            "target_user_id": target_user_id,
            "punishment_type": punishment_type.value,
            "reason": reason,
        }
        if origin_channel_id is not None:
            detail["origin_channel_id"] = origin_channel_id
        if expires_at is not None:
            detail["expires_at"] = expires_at.isoformat()
        await uow.operation_log.log_operation(
            operator_id=moderator_id,
            operator_name=moderator_name,
            operator_display_name=moderator_display_name,
            op_type=LogOperationType.PUNISHMENT,
            action=action,
            target_type="global_proposal_punishment",
            target_id=punishment_id,
            guild_id=guild_id,
            detail=json.dumps(detail, ensure_ascii=False),
        )

    async def handle_remove_punishment(
        self,
        interaction: discord.Interaction,
        thread: discord.Thread,
        moderator: discord.Member,
        target_user: discord.User | discord.Member,
        reason: str,
    ):
        """执行解除处罚的完整业务流程"""
        try:
            # 查询是否有记录
            async with UnitOfWork(self.bot.db_handler) as uow:
                activity = await uow.user_activity.get_user_activity(target_user.id, thread.id)
                if not activity:
                    # 没有记录，直接返回错误信息
                    await interaction.followup.send(
                        f"用户 {target_user.mention} 在当前帖子中没有处罚记录。", ephemeral=True
                    )
                    return

                # 转换为DTO以便在UOW生命周期外使用
                activity_dto = UserActivityDto.model_validate(activity)

            # 检查是否有处罚（validation=0 或 mute_end_time 不为空）
            has_punishment = (activity_dto.validation == 0) or (
                activity_dto.mute_end_time is not None
            )
            if not has_punishment:
                # 没有处罚，发送提示信息
                await interaction.followup.send(
                    f"用户 {target_user.mention} 在当前帖子中没有处罚记录。", ephemeral=True
                )
                return

            # 清空处罚
            async with UnitOfWork(self.bot.db_handler) as uow:
                await uow.user_activity.clear_punishment(target_user.id, thread.id)
                await uow.commit()

            # 内存缓存同步（通知监听器更新 active_mutes）
            self.bot.dispatch("thread_mute_updated", thread.id, target_user.id, None)

            # 发送公示
            embed = PunishmentEmbedBuilder.create_unpunish_embed(moderator, target_user, reason)
            await self.bot.api_scheduler.submit(thread.send(embed=embed), priority=5)

        except Exception as e:
            logger.error(f"执行解除处罚逻辑失败: {e}", exc_info=True)
            # 发送错误信息
            await interaction.followup.send(f"解除处罚过程中发生错误: {str(e)}", ephemeral=True)
