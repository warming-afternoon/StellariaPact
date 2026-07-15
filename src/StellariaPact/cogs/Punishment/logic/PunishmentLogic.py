import logging
from datetime import datetime

import discord

from StellariaPact.dto.UserActivityDto import UserActivityDto
from StellariaPact.share import StellariaPactBot, UnitOfWork

from ..views.PunishmentEmbedBuilder import PunishmentEmbedBuilder

logger = logging.getLogger(__name__)


class PunishmentLogic:
    def __init__(self, bot: StellariaPactBot):
        self.bot = bot

    async def apply_global_voting_restriction(
        self,
        *,
        target_user_id: int,
        moderator_id: int,
        origin_guild_id: int,
        origin_channel_id: int,
        reason: str,
        evidence_url: str | None,
        evidence_filename: str | None,
    ) -> None:
        """永久剥夺用户在本机器人范围内的投票资格。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            await uow.global_voting_restriction.create_restriction(
                target_user_id=target_user_id,
                moderator_id=moderator_id,
                origin_guild_id=origin_guild_id,
                origin_channel_id=origin_channel_id,
                reason=reason,
                evidence_url=evidence_url,
                evidence_filename=evidence_filename,
            )
            await uow.commit()

    async def lift_global_voting_restriction(
        self,
        *,
        target_user_id: int,
        lifted_by_id: int,
        lift_reason: str,
    ) -> datetime:
        """解除用户的机器人全局投票资格限制。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            restriction = await uow.global_voting_restriction.lift_restriction(
                target_user_id=target_user_id,
                lifted_by_id=lifted_by_id,
                lift_reason=lift_reason,
            )
            original_created_at = restriction.created_at
            await uow.commit()
            return original_created_at

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
