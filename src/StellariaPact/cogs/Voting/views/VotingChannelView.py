import discord

from StellariaPact.cogs.Voting.dto import VoteDetailDto
from StellariaPact.share import StellariaPactBot, safeDefer


class VotingChannelView(discord.ui.View):
    """
    投票频道镜像面板。
    """
    def __init__(self, bot: "StellariaPactBot", vote_details: VoteDetailDto | None = None):
        super().__init__(timeout=None)
        self.bot = bot
        self._build_ui(vote_details)

    def _build_ui(self, vote_details: VoteDetailDto | None):
        self.clear_items()

        is_active = vote_details.status == 1 if vote_details else True

        # --- 第一行 ---
        btn_manage = discord.ui.Button(
            label="投票管理", style=discord.ButtonStyle.primary, row=0, custom_id="mirror_btn_manage_vote", disabled=not is_active
        )
        btn_manage.callback = self.manage_vote
        self.add_item(btn_manage)

        btn_rules = discord.ui.Button(
            label="规则管理", style=discord.ButtonStyle.secondary, row=0, custom_id="mirror_btn_manage_rules"
        )
        btn_rules.callback = self.manage_rules
        self.add_item(btn_rules)

        # --- 第二行 ---
        btn_normal = discord.ui.Button(
            label="创建普通投票", style=discord.ButtonStyle.success, row=1, custom_id="mirror_btn_create_normal", disabled=not is_active
        )
        btn_normal.callback = self.create_normal
        self.add_item(btn_normal)

        btn_objection = discord.ui.Button(
            label="创建异议", style=discord.ButtonStyle.danger, row=1, custom_id="mirror_btn_create_objection", disabled=not is_active
        )
        btn_objection.callback = self.create_objection
        self.add_item(btn_objection)

    async def manage_vote(self, interaction: discord.Interaction):
        await safeDefer(interaction, ephemeral=True)
        self.bot.dispatch("mirror_panel_clicked", interaction, "manage_vote")

    async def manage_rules(self, interaction: discord.Interaction):
        await safeDefer(interaction, ephemeral=True)
        self.bot.dispatch("mirror_panel_clicked", interaction, "manage_rules")

    async def create_normal(self, interaction: discord.Interaction):
        # 弹窗不能 defer
        self.bot.dispatch("mirror_panel_clicked", interaction, "create_normal")

    async def create_objection(self, interaction: discord.Interaction):
        self.bot.dispatch("mirror_panel_clicked", interaction, "create_objection")
