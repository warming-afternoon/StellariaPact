import asyncio
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

    async def _edit_thread_tags(self, thread_id: int):
        try:
            if not hasattr(self.bot, "config"):
                logger.warning("机器人配置未加载，无法修改帖子标签。")
                return

            tags_config = self.bot.config.get("tags", {})
            discussion_tag_id = tags_config.get("discussion")
            executing_tag_id = tags_config.get("executing")

            if not discussion_tag_id or not executing_tag_id:
                logger.warning("讨论或执行中标签ID未在配置中找到，无法修改帖子标签。")
                return

            thread = await self.bot.fetch_channel(thread_id)
            if not isinstance(thread, discord.Thread):
                return

            # 确保父频道是论坛频道
            if not isinstance(thread.parent, discord.ForumChannel):
                logger.warning(f"帖子 {thread_id} 的父频道不是论坛频道，无法修改标签。")
                return

            discussion_tag = thread.parent.get_tag(int(discussion_tag_id))
            executing_tag = thread.parent.get_tag(int(executing_tag_id))

            if not executing_tag:
                logger.warning(f"在论坛频道 {thread.parent.name} 中未找到执行中标签。")
                return

            new_tags = [tag for tag in thread.applied_tags if tag != discussion_tag]
            new_tags.append(executing_tag)

            await self.bot.api_scheduler.submit(thread.edit(applied_tags=new_tags), 2)

        except discord.HTTPException as e:
            logger.error(f"修改帖子 {thread_id} 标签时发生API错误: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"修改帖子 {thread_id} 标签时发生未知错误: {e}", exc_info=True)

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

        await self.bot.api_scheduler.submit(safeDefer(interaction, ephemeral=True), 1)

        thread_id_to_update: int | None = None
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

            if updated_status == 1:  # 1: 已完成
                proposal = await uow.moderation.get_proposal_by_id(updated_session.targetId)
                if proposal:
                    proposal.status = 1  # 1: 执行中
                    thread_id_to_update = proposal.discussionThreadId

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
            tasks = [
                self.bot.api_scheduler.submit(
                    interaction.edit_original_response(embed=embed, view=self), 1
                )
            ]
            if thread_id_to_update:
                tasks.append(self._edit_thread_tags(thread_id_to_update))
            await asyncio.gather(*tasks)
        else:
            await self.bot.api_scheduler.submit(
                interaction.edit_original_response(embed=embed, view=self), 1
            )

    @discord.ui.button(label="取消", style=discord.ButtonStyle.red, custom_id="moderation_cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not self.bot.user:
            return await self.bot.api_scheduler.submit(
                interaction.response.send_message("无法验证您的身份。", ephemeral=True), 1
            )

        if not interaction.message:
            return await self.bot.api_scheduler.submit(
                interaction.response.send_message("无法找到原始消息。", ephemeral=True), 1
            )

        await self.bot.api_scheduler.submit(safeDefer(interaction, ephemeral=True), 1)

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
