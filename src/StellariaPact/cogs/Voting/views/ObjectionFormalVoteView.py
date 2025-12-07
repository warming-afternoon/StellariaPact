import logging

import discord

from StellariaPact.share import StellariaPactBot, safeDefer

logger = logging.getLogger(__name__)


class ObjectionFormalVoteView(discord.ui.View):
    """
    用于“正式异议投票”的公开视图。
    采用“管理投票”模式。
    """

    def __init__(self, bot: "StellariaPactBot"):
        super().__init__(timeout=None)
        self.bot = bot

    # -----------------
    # 回调和辅助函数
    # -----------------

    async def _on_vote_callback(
        self,
        inner_interaction: discord.Interaction,
        original_message_id: int,
        choice: int,
    ):
        """处理同意或反对投票的回调"""
        await safeDefer(inner_interaction, ephemeral=True)
        self.bot.dispatch(
            "objection_formal_vote_record",
            inner_interaction,
            original_message_id,
            choice,
        )

    async def _on_abstain_callback(
        self, inner_interaction: discord.Interaction, original_message_id: int
    ):
        """处理弃权投票的回调"""
        await safeDefer(inner_interaction, ephemeral=True)
        self.bot.dispatch("objection_formal_vote_abstain", inner_interaction, original_message_id)

    @discord.ui.button(
        label="管理投票",
        style=discord.ButtonStyle.primary,
        custom_id="objection_formal_manage_vote",
    )
    async def manage_vote_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """
        处理用户点击“管理投票”按钮的事件。
        将弹出一个临时的、仅用户可见的视图，其中包含投票资格和投票选项。
        """
        await safeDefer(interaction, ephemeral=True)
        self.bot.dispatch("objection_formal_vote_manage", interaction)
