from typing import cast

import discord

from StellariaPact.cogs.Voting.Cog import Voting
from StellariaPact.cogs.Voting.views.VoteEmbedBuilder import VoteEmbedBuilder
from StellariaPact.cogs.Voting.views.VotingChoiceView import VotingChoiceView
from StellariaPact.share.auth.PermissionGuard import PermissionGuard
from StellariaPact.share.DiscordUtils import send_private_panel
from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot


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
        处理用户点击"管理投票"按钮的事件。
        对所有用户，都显示一个包含其投票资格和投票选项的统一视图。
        如果用户是管理员，该视图会额外包含管理按钮。
        """
        await safeDefer(interaction, ephemeral=True)

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

            can_manage = await PermissionGuard.can_manage_vote(interaction)

            choice_view = VotingChoiceView(
                bot=self.bot,
                logic=voting_cog.logic,
                original_message_id=interaction.message.id,
                thread_id=interaction.channel.id,
                is_eligible=panel_data.is_eligible,
                is_vote_active=panel_data.is_vote_active,
                can_manage=can_manage,
            )
            await send_private_panel(self.bot, interaction, embed=embed, view=choice_view)
        except Exception as e:
            await interaction.followup.send(f"处理投票管理面板时出错: {e}", ephemeral=True)

    @discord.ui.button(
        label="对提案发起异议",
        style=discord.ButtonStyle.danger,
        custom_id="vote_view_raise_objection",
        row=0,
    )
    async def raise_objection_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """
        点击后直接弹出异议模态框
        """
        # 派发事件，由 Voting/Cog.py 中的监听器统一处理
        self.bot.dispatch("vote_view_raise_objection_clicked", interaction)
