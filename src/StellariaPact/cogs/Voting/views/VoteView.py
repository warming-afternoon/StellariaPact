import discord

from StellariaPact.share import StellariaPactBot, safeDefer


class VoteView(discord.ui.View):
    """
    投票面板的视图，包含四个按钮，分为两行。
    第一行：投票管理、规则管理
    第二行：创建普通投票、创建异议
    """

    def __init__(self, bot: StellariaPactBot):
        super().__init__(timeout=None)  # 持久化视图
        self.bot = bot

    # --- 第一行 ---
    @discord.ui.button(
        label="投票管理",
        style=discord.ButtonStyle.primary,
        row=0,
        custom_id="btn_manage_vote",
    )
    async def manage_vote(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safeDefer(interaction, ephemeral=True)
        self.bot.dispatch("panel_manage_vote_clicked", interaction)

    @discord.ui.button(
        label="规则管理",
        style=discord.ButtonStyle.secondary,
        row=0,
        custom_id="btn_manage_rules",
    )
    async def manage_rules(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safeDefer(interaction, ephemeral=True)
        self.bot.dispatch("panel_manage_rules_clicked", interaction)

    # --- 第二行 ---
    @discord.ui.button(
        label="创建普通投票",
        style=discord.ButtonStyle.success,
        row=1,
        custom_id="btn_create_normal",
    )
    async def create_normal(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.bot.dispatch("panel_create_option_clicked", interaction, option_type=0)

    @discord.ui.button(
        label="创建异议",
        style=discord.ButtonStyle.danger,
        row=1,
        custom_id="btn_create_objection",
    )
    async def create_objection(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.bot.dispatch("panel_create_option_clicked", interaction, option_type=1)
