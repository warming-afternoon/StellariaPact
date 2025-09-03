from typing import cast

import discord

from StellariaPact.share.DiscordUtils import send_private_panel

from ....share.auth.RoleGuard import RoleGuard
from ....share.SafeDefer import safeDefer
from ....share.StellariaPactBot import StellariaPactBot
from ..Cog import Voting
from ..views.VotingChoiceView import VotingChoiceView
from .VoteEmbedBuilder import VoteEmbedBuilder


class VoteView(discord.ui.View):
    """
    投票面板的视图，包含投票按钮。
    """

    def __init__(self, bot: StellariaPactBot):
        super().__init__(timeout=None)  # 持久化视图
        self.bot = bot

    @discord.ui.button(
        label="管理投票", style=discord.ButtonStyle.primary, custom_id="manage_vote_button"
    )
    async def vote_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        处理用户点击“管理投票”按钮的事件。
        对所有用户，都显示一个包含其投票资格和投票选项的统一视图。
        如果用户是管理员，该视图会额外包含管理按钮。
        """
        await self.bot.api_scheduler.submit(safeDefer(interaction, ephemeral=True), priority=1)

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

        voting_cog = cast(Voting, self.bot.get_cog("Voting"))
        if not voting_cog:
            await interaction.followup.send("投票系统组件未就绪，请联系管理员。", ephemeral=True)
            return

        try:
            panel_data = await voting_cog.logic.prepare_voting_choice_data(
                user_id=interaction.user.id,
                thread_id=interaction.channel.id,
                message_id=interaction.message.id,
            )

            embed = VoteEmbedBuilder.create_management_panel_embed(
                jump_url=interaction.message.jump_url, panel_data=panel_data
            )

            is_admin = RoleGuard.hasRoles(
                interaction, "councilModerator", "executionAuditor", "stewards"
            )
            if not panel_data.is_eligible and not is_admin:
                await self.bot.api_scheduler.submit(
                    interaction.followup.send(embed=embed, ephemeral=True), priority=1
                )
                return

            choice_view = VotingChoiceView(
                interaction,
                interaction.message.id,
                is_eligible=panel_data.is_eligible,
                is_vote_active=panel_data.is_vote_active,
                logic=voting_cog.logic,
            )
            await send_private_panel(self.bot, interaction, embed=embed, view=choice_view)
        except Exception as e:
            await interaction.followup.send(f"处理投票管理面板时出错: {e}", ephemeral=True)
