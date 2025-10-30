import discord
from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot


class VotingChannelView(discord.ui.View):
    """
    用于投票频道的公开投票视图。
    """

    def __init__(self, bot: "StellariaPactBot"):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="管理投票",
        style=discord.ButtonStyle.primary,
        custom_id="voting_channel_manage_vote",
    )
    async def manage_vote_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """
        处理"管理投票"按钮。它会查找关联的帖子内投票，并触发其管理流程。
        """
        await safeDefer(interaction, ephemeral=True)
        self.bot.dispatch("voting_channel_manage_vote_clicked", interaction)

    @discord.ui.button(
        label="对提案发起异议",
        style=discord.ButtonStyle.danger,
        custom_id="voting_channel_raise_objection",
    )
    async def raise_objection_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """
        点击后弹出异议模态框
        """
        self.bot.dispatch("voting_channel_raise_objection_clicked", interaction)