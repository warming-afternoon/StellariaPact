import discord

from StellariaPact.share import StellariaPactBot, safeDefer


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
        """
        await safeDefer(interaction, ephemeral=True)
        self.bot.dispatch("manage_vote_button_clicked", interaction)

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
        点击后弹出异议模态框
        """
        self.bot.dispatch("vote_view_raise_objection_clicked", interaction)
