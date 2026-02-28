import discord

from StellariaPact.share import StellariaPactBot, safeDefer


class VotingChannelView(discord.ui.View):
    """
    投票频道镜像面板。
    """
    def __init__(self, bot: "StellariaPactBot"):
        super().__init__(timeout=None)
        self.bot = bot

    # --- 第一行 ---
    @discord.ui.button(label="投票管理", style=discord.ButtonStyle.primary, row=0, custom_id="mirror_btn_manage_vote")
    async def manage_vote(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safeDefer(interaction, ephemeral=True)
        self.bot.dispatch("mirror_panel_clicked", interaction, "manage_vote")

    @discord.ui.button(label="规则管理", style=discord.ButtonStyle.secondary, row=0, custom_id="mirror_btn_manage_rules")
    async def manage_rules(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safeDefer(interaction, ephemeral=True)
        self.bot.dispatch("mirror_panel_clicked", interaction, "manage_rules")

    # --- 第二行 ---
    @discord.ui.button(label="创建普通投票", style=discord.ButtonStyle.success, row=1, custom_id="mirror_btn_create_normal")
    async def create_normal(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 弹窗不能 defer
        self.bot.dispatch("mirror_panel_clicked", interaction, "create_normal")

    @discord.ui.button(label="创建异议", style=discord.ButtonStyle.danger, row=1, custom_id="mirror_btn_create_objection")
    async def create_objection(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.bot.dispatch("mirror_panel_clicked", interaction, "create_objection")
