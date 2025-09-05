import logging

import discord

from StellariaPact.share.auth.RoleGuard import RoleGuard
from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.UnitOfWork import UnitOfWork

from ..qo.BuildConfirmationEmbedQo import BuildConfirmationEmbedQo
from .ModerationEmbedBuilder import ModerationEmbedBuilder

logger = logging.getLogger(__name__)


class ConfirmationView(discord.ui.View):
    def __init__(self, bot: StellariaPactBot):
        super().__init__(timeout=None)
        self.bot = bot

    def _disable_all_buttons(self):
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True


    @discord.ui.button(
        label="确认", style=discord.ButtonStyle.green, custom_id="moderation_confirm"
    )
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not self.bot.user:
            return await self.bot.api_scheduler.submit(
                interaction.response.send_message("无法验证您的身份。", ephemeral=True), 1
            )

        if not interaction.message:
            return await self.bot.api_scheduler.submit(
                interaction.response.send_message("无法找到原始消息。", ephemeral=True), 1
            )

        await safeDefer(interaction, ephemeral=True)

        updated_status: int = 0

        async with UnitOfWork(self.bot.db_handler) as uow:
            session = await uow.moderation.get_confirmation_session_by_message_id(
                interaction.message.id
            )

            if not session:
                return await self.bot.api_scheduler.submit(
                    interaction.followup.send("未找到相关的确认会话。", ephemeral=True), 1
                )

            if interaction.user.id in session.confirmedParties.values():
                return await self.bot.api_scheduler.submit(
                    interaction.followup.send("您已经确认过了，不能重复确认。", ephemeral=True),
                    1,
                )

            unconfirmed_roles = set(session.requiredRoles) - set(session.confirmedParties.keys())
            role_to_confirm = next(
                (
                    role_key
                    for role_key in unconfirmed_roles
                    if RoleGuard.hasRoles(interaction, role_key)
                ),
                None,
            )

            if not role_to_confirm:
                return await self.bot.api_scheduler.submit(
                    interaction.followup.send("您没有权限执行此操作", ephemeral=True),
                    1,
                )

            updated_session = await uow.moderation.add_confirmation(
                session, role_to_confirm, interaction.user.id
            )
            updated_status = updated_session.status

            # 准备 Embed QO
            role_display_names = {}
            if interaction.guild and hasattr(self.bot, "config"):
                roles_config = self.bot.config.get("roles", {})
                for role_key in updated_session.requiredRoles:
                    role_id = roles_config.get(role_key)
                    if role_id:
                        role = interaction.guild.get_role(int(role_id))
                        role_display_names[role_key] = role.name if role else role_key
                    else:
                        role_display_names[role_key] = role_key

            qo = BuildConfirmationEmbedQo(
                status=updated_session.status,
                canceler_id=updated_session.cancelerId,
                confirmed_parties=updated_session.confirmedParties or {},
                required_roles=updated_session.requiredRoles,
                role_display_names=role_display_names,
            )
            embed = ModerationEmbedBuilder.build_confirmation_embed(qo, self.bot.user)

            await uow.commit()

        # --- 事务外执行API调用 ---
        if updated_status == 1:  # 已完成
            self._disable_all_buttons()
            await self.bot.api_scheduler.submit(
                interaction.edit_original_response(embed=embed, view=self), 1
            )
            self.bot.dispatch("confirmation_completed", updated_session)
        else:
            await self.bot.api_scheduler.submit(
                interaction.edit_original_response(embed=embed, view=self), 1
            )

    @discord.ui.button(label="反对", style=discord.ButtonStyle.red, custom_id="moderation_cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not self.bot.user:
            return await self.bot.api_scheduler.submit(
                interaction.response.send_message("无法验证您的身份。", ephemeral=True), 1
            )

        if not interaction.message:
            return await self.bot.api_scheduler.submit(
                interaction.response.send_message("无法找到原始消息。", ephemeral=True), 1
            )

        await safeDefer(interaction, ephemeral=True)

        async with UnitOfWork(self.bot.db_handler) as uow:
            session = await uow.moderation.get_confirmation_session_by_message_id(
                interaction.message.id
            )

            if not session:
                return await self.bot.api_scheduler.submit(
                    interaction.followup.send("未找到相关的确认会话。", ephemeral=True), 1
                )

            # 检查用户是否有权取消
            if not RoleGuard.hasRoles(interaction, *session.requiredRoles):
                return await self.bot.api_scheduler.submit(
                    interaction.followup.send("您没有权限取消此操作。", ephemeral=True), 1
                )

            updated_session = await uow.moderation.cancel_confirmation_session(
                session, interaction.user.id
            )

            # 准备角色显示名称的映射
            role_display_names = {}
            if interaction.guild and hasattr(self.bot, "config"):
                roles_config = self.bot.config.get("roles", {})
                for role_key in updated_session.requiredRoles:
                    role_id = roles_config.get(role_key)
                    if role_id:
                        role = interaction.guild.get_role(int(role_id))
                        role_display_names[role_key] = role.name if role else role_key
                    else:
                        role_display_names[role_key] = role_key

            qo = BuildConfirmationEmbedQo(
                status=updated_session.status,
                canceler_id=updated_session.cancelerId,
                confirmed_parties=updated_session.confirmedParties or {},
                required_roles=updated_session.requiredRoles,
                role_display_names=role_display_names,
            )

            if not self.bot.user:
                return await self.bot.api_scheduler.submit(
                    interaction.followup.send("机器人尚未准备好，无法构建消息。", ephemeral=True),
                    1,
                )

            embed = ModerationEmbedBuilder.build_confirmation_embed(qo, self.bot.user)

            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True

            await uow.commit()

        await self.bot.api_scheduler.submit(
            interaction.edit_original_response(embed=embed, view=self), 1
        )
