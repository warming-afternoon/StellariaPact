import logging

import discord

from StellariaPact.share.auth.RoleGuard import RoleGuard
from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.UnitOfWork import UnitOfWork

from .dto import ConfirmationEmbedData
from .ModerationEmbedBuilder import ModerationEmbedBuilder

logger = logging.getLogger(__name__)


class ConfirmationView(discord.ui.View):
    def __init__(self, bot: StellariaPactBot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="确认", style=discord.ButtonStyle.green, custom_id="moderation_confirm"
    )
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):


        if not isinstance(interaction.user, discord.Member) or not self.bot.user:
            return await self.bot.api_scheduler.submit(
                interaction.response.send_message("无法验证您的身份。", ephemeral=True), 1
            )

        if not interaction.message:
            return await self.bot.api_scheduler.submit(
                interaction.response.send_message("无法找到原始消息。", ephemeral=True), 1
            )
        
        await self.bot.api_scheduler.submit(
            safeDefer(interaction, ephemeral=True), 1
        )

        async with UnitOfWork(self.bot.db_handler) as uow:
            session = await uow.moderation.get_confirmation_session_by_message_id(
                interaction.message.id
            )

            if not session:
                return await self.bot.api_scheduler.submit(
                    interaction.followup.send("未找到相关的确认会话。", ephemeral=True), 1
                )

            # 使用 RoleGuard 检查用户是否有权确认
            unconfirmed_roles = set(session.requiredRoles) - set(
                session.confirmedParties.keys()
            )
            
            role_to_confirm = None
            for role_key in unconfirmed_roles:
                if RoleGuard.hasRoles(interaction, role_key):
                    role_to_confirm = role_key
                    break

            if not role_to_confirm:
                return await self.bot.api_scheduler.submit(
                    interaction.followup.send(
                        "您没有权限执行此操作，或者您代表的角色已经确认过了。", ephemeral=True
                    ),
                    1,
                )
            updated_session = await uow.moderation.add_confirmation(
                session, role_to_confirm, interaction.user.id
            )

            embed_data = ConfirmationEmbedData(
                status=updated_session.status,
                canceler_id=updated_session.cancelerId,
                confirmed_parties=updated_session.confirmedParties or {},
                required_roles=updated_session.requiredRoles,
            )
            embed = ModerationEmbedBuilder.build_confirmation_embed(
                embed_data, self.bot.user
            )

            if embed_data.status == 1:
                for item in self.children:
                    if isinstance(item, discord.ui.Button):
                        item.disabled = True
                # 更新提案状态
                await uow.moderation.update_proposal_status_by_thread_id(
                    updated_session.targetId, 1 # 1: 执行中
                )

            await uow.commit()

        await self.bot.api_scheduler.submit(
            interaction.edit_original_response(embed=embed, view=self), 1
        )

    @discord.ui.button(
        label="取消", style=discord.ButtonStyle.red, custom_id="moderation_cancel"
    )
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        if not isinstance(interaction.user, discord.Member) or not self.bot.user:
            return await self.bot.api_scheduler.submit(
                interaction.response.send_message("无法验证您的身份。", ephemeral=True), 1
            )

        if not interaction.message:
            return await self.bot.api_scheduler.submit(
                interaction.response.send_message("无法找到原始消息。", ephemeral=True), 1
            )

        await self.bot.api_scheduler.submit(
            safeDefer(interaction, ephemeral=True), 1
        )

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

            embed_data = ConfirmationEmbedData(
                status=updated_session.status,
                canceler_id=updated_session.cancelerId,
                confirmed_parties=updated_session.confirmedParties or {},
                required_roles=updated_session.requiredRoles,
            )
            embed = ModerationEmbedBuilder.build_confirmation_embed(
                embed_data, self.bot.user
            )

            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            
            await uow.commit()

        await self.bot.api_scheduler.submit(
            interaction.edit_original_response(embed=embed, view=self), 1
        )