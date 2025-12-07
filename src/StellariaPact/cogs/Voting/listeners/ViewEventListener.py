import logging

import discord
from discord.ext import commands

from StellariaPact.cogs.Voting.qo import DeleteVoteQo, RecordVoteQo
from StellariaPact.cogs.Voting.views import VoteEmbedBuilder, VotingChoiceView
from StellariaPact.cogs.Voting.VotingLogic import VotingLogic
from StellariaPact.share import DiscordUtils, PermissionGuard, StellariaPactBot, safeDefer

logger = logging.getLogger(__name__)


class ViewEventListener(commands.Cog):
    """
    专门监听由 Views, Modals, 等UI组件派发的自定义事件。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.logic = VotingLogic(bot)

    async def _update_private_panel(
        self,
        interaction: discord.Interaction,
        thread_id: int,
        message_id: int,
        view: discord.ui.View,
    ):
        """通用私有面板更新"""
        if interaction.message:
            panel_data = await self.logic.prepare_voting_choice_data(
                interaction.user.id, thread_id, message_id
            )
            new_embed = VoteEmbedBuilder.create_management_panel_embed(
                jump_url=f"https://discord.com/channels/{panel_data.guild_id}/{panel_data.thread_id}/{panel_data.message_id}",
                panel_data=panel_data,
            )
            await interaction.edit_original_response(embed=new_embed, view=view)

    @commands.Cog.listener()
    async def on_vote_choice_recorded(
        self,
        *,
        interaction: discord.Interaction,
        message_id: int,
        thread_id: int,
        choice: int,
        choice_index: int,
        view: discord.ui.View,
    ):
        await safeDefer(interaction)
        try:
            vote_details = await self.logic.record_vote_and_get_details(
                RecordVoteQo(
                    user_id=interaction.user.id,
                    message_id=message_id,
                    thread_id=thread_id,
                    choice=choice,
                    choice_index=choice_index,
                )
            )
            await self._update_private_panel(interaction, thread_id, message_id, view)
            self.bot.dispatch("vote_details_updated", vote_details)
        except PermissionError as e:
            await interaction.followup.send(str(e), ephemeral=True)
        except Exception as e:
            logger.error(f"记录投票时发生错误: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.followup.send("记录投票时发生错误。", ephemeral=True)

    @commands.Cog.listener()
    async def on_vote_choice_abstained(
        self,
        *,
        interaction: discord.Interaction,
        message_id: int,
        thread_id: int,
        choice_index: int,
        view: discord.ui.View,
    ):
        await safeDefer(interaction)
        try:
            vote_details = await self.logic.delete_vote_and_get_details(
                DeleteVoteQo(
                    user_id=interaction.user.id,
                    message_id=message_id,
                    choice_index=choice_index,
                )
            )
            await self._update_private_panel(interaction, thread_id, message_id, view)
            self.bot.dispatch("vote_details_updated", vote_details)
        except Exception as e:
            logger.error(f"弃权时发生错误: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.followup.send("弃权时发生错误。", ephemeral=True)

    @commands.Cog.listener()
    async def on_vote_time_adjusted(
        self,
        *,
        interaction: discord.Interaction,
        thread_id: int,
        message_id: int,
        hours_to_adjust: int,
    ):
        try:
            await self.logic.adjust_vote_time(
                thread_id=thread_id,
                message_id=message_id,
                hours_to_adjust=hours_to_adjust,
                operator=interaction.user,
            )
            await self.bot.api_scheduler.submit(
                interaction.followup.send("投票时间已成功调整。", ephemeral=True), priority=1
            )
        except Exception as e:
            logger.error(f"调整投票时间时出错: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send(f"操作失败: {e}", ephemeral=True),
                priority=1,
            )

    @commands.Cog.listener()
    async def on_vote_reopened(
        self,
        *,
        interaction: discord.Interaction,
        thread_id: int,
        message_id: int,
        hours_to_add: int,
    ):
        try:
            await self.logic.reopen_vote(
                thread_id=thread_id,
                message_id=message_id,
                hours_to_add=hours_to_add,
                operator=interaction.user,
            )
            await self.bot.api_scheduler.submit(
                interaction.followup.send("投票已重新开启。", ephemeral=True), priority=1
            )
        except Exception as e:
            logger.error(f"重新开启投票时出错: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send(f"操作失败: {e}", ephemeral=True),
                priority=1,
            )

    async def _handle_toggle_action(
        self,
        interaction: discord.Interaction,
        message_id: int,
        toggle_method_name: str,
        setting_name: str,
    ):
        """通用处理切换设置的逻辑"""
        await safeDefer(interaction, ephemeral=True)
        try:
            # Dynamically call the toggle method on the logic instance
            toggle_method = getattr(self.logic, toggle_method_name)
            await toggle_method(message_id, operator=interaction.user)

            await self.bot.api_scheduler.submit(
                interaction.followup.send(f"已成功切换 **{setting_name}** 状态。", ephemeral=True),
                priority=1,
            )
        except Exception as e:
            logger.error(f"处理切换 {setting_name} 时出错: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send(
                    f"切换 {setting_name} 状态时发生内部错误。", ephemeral=True
                ),
                priority=1,
            )

    @commands.Cog.listener()
    async def on_vote_anonymous_toggled(
        self, *, interaction: discord.Interaction, message_id: int, thread_id: int
    ):
        await self._handle_toggle_action(interaction, message_id, "toggle_anonymous", "匿名投票")

    @commands.Cog.listener()
    async def on_vote_realtime_toggled(
        self, *, interaction: discord.Interaction, message_id: int, thread_id: int
    ):
        await self._handle_toggle_action(interaction, message_id, "toggle_realtime", "实时票数")

    @commands.Cog.listener()
    async def on_vote_notify_toggled(
        self, *, interaction: discord.Interaction, message_id: int, thread_id: int
    ):
        await self._handle_toggle_action(interaction, message_id, "toggle_notify", "投票结束通知")

    @commands.Cog.listener()
    async def on_manage_vote_button_clicked(self, interaction: discord.Interaction):
        """
        处理来自 VoteView 的 manage_vote_button 点击事件。
        """
        if not interaction.channel or not isinstance(interaction.channel, discord.Thread):
            await self.bot.api_scheduler.submit(
                interaction.followup.send("此功能仅在帖子内可用。", ephemeral=True), priority=1
            )
            return

        if not interaction.message:
            await self.bot.api_scheduler.submit(
                interaction.followup.send("无法找到原始投票消息，请重试。", ephemeral=True),
                priority=1,
            )
            return

        try:
            panel_data = await self.logic.prepare_voting_choice_data(
                user_id=interaction.user.id,
                thread_id=interaction.channel.id,
                message_id=interaction.message.id,
            )

            embed = VoteEmbedBuilder.create_management_panel_embed(
                jump_url=interaction.message.jump_url, panel_data=panel_data
            )

            can_manage = await PermissionGuard.can_manage_vote(interaction)

            choice_view = VotingChoiceView(
                bot=self.bot,
                original_message_id=interaction.message.id,
                thread_id=interaction.channel.id,
                panel_data=panel_data,
                can_manage=can_manage,
            )
            await DiscordUtils.send_private_panel(
                self.bot, interaction, embed=embed, view=choice_view
            )
        except Exception as e:
            logger.error(f"处理管理投票面板时出错: {e}", exc_info=True)
            await interaction.followup.send(f"处理投票管理面板时出错: {e}", ephemeral=True)
