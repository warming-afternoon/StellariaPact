import discord

from StellariaPact.share import StellariaPactBot, safeDefer


class ObjectionSupportView(discord.ui.View):
    """异议支持（附议）面板"""

    def __init__(self, bot: StellariaPactBot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="支持异议创建",
        style=discord.ButtonStyle.success,
        custom_id="obj_support_btn"
    )
    async def support_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safeDefer(interaction, ephemeral=True)
        # 将点击事件分发给 InnerEventListener
        self.bot.dispatch("objection_support_clicked", interaction)
