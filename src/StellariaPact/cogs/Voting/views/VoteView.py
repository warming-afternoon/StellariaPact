import discord

from StellariaPact.cogs.Voting.dto import VoteDetailDto
from StellariaPact.share import StellariaPactBot, safeDefer


class VoteView(discord.ui.View):
    """
    投票面板的视图，包含四个按钮，分为两行。
    第一行：投票管理、规则管理
    第二行：创建普通投票、创建异议
    """

    def __init__(self, bot: StellariaPactBot, vote_details: VoteDetailDto | None = None):
        super().__init__(timeout=None)  # 持久化视图
        self.bot = bot
        self._build_ui(vote_details)

    def _build_ui(self, vote_details: VoteDetailDto | None):
        self.clear_items()
        
        # 判断当前投票是否活跃。如果未提供 vote_details (如 setup 注册时)，则默认活跃。
        is_active = vote_details.status == 1 if vote_details else True

        # --- 第一行 ---
        btn_manage = discord.ui.Button(
            label="投票管理", style=discord.ButtonStyle.primary, row=0, custom_id="btn_manage_vote", disabled=not is_active
        )
        btn_manage.callback = self.manage_vote
        self.add_item(btn_manage)

        btn_rules = discord.ui.Button(
            label="规则管理", style=discord.ButtonStyle.secondary, row=0, custom_id="btn_manage_rules"
        )
        btn_rules.callback = self.manage_rules
        self.add_item(btn_rules)

        # --- 第二行 ---
        btn_normal = discord.ui.Button(
            label="创建普通投票", style=discord.ButtonStyle.success, row=1, custom_id="btn_create_normal", disabled=not is_active
        )
        btn_normal.callback = self.create_normal
        self.add_item(btn_normal)

        btn_objection = discord.ui.Button(
            label="创建异议", style=discord.ButtonStyle.danger, row=1, custom_id="btn_create_objection", disabled=not is_active
        )
        btn_objection.callback = self.create_objection
        self.add_item(btn_objection)

    async def manage_vote(self, interaction: discord.Interaction):
        await safeDefer(interaction, ephemeral=True)
        self.bot.dispatch("panel_manage_vote_clicked", interaction)

    async def manage_rules(self, interaction: discord.Interaction):
        await safeDefer(interaction, ephemeral=True)
        self.bot.dispatch("panel_manage_rules_clicked", interaction)

    async def create_normal(self, interaction: discord.Interaction):
        self.bot.dispatch("panel_create_option_clicked", interaction, option_type=0)

    async def create_objection(self, interaction: discord.Interaction):
        self.bot.dispatch("panel_create_option_clicked", interaction, option_type=1)
