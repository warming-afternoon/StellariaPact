import logging
from typing import TYPE_CHECKING, Literal

import discord

from ....share.SafeDefer import safeDefer

if TYPE_CHECKING:
    from ....share.StellariaPactBot import StellariaPactBot


logger = logging.getLogger(__name__)


class ObjectionCreationVoteView(discord.ui.View):
    """
    异议支持收集阶段的公开视图。
    """

    def __init__(self, bot: "StellariaPactBot"):
        super().__init__(timeout=None)  # 持久化视图
        self.bot = bot

    @discord.ui.button(
        label="支持此异议",
        style=discord.ButtonStyle.primary,
        custom_id="objection_creation_support",
    )
    async def support_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """处理“支持”按钮点击事件"""
        await self._handle_choice(interaction, "support")

    @discord.ui.button(
        label="撤回支持",
        style=discord.ButtonStyle.primary,
        custom_id="objection_creation_withdraw",
    )
    async def withdraw_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """处理“撤回支持”按钮点击事件"""
        await self._handle_choice(interaction, "withdraw")

    async def _handle_choice(
        self, interaction: discord.Interaction, choice: Literal["support", "withdraw"]
    ):
        """
        统一处理用户的“支持”或“撤回”操作。
        """
        # 立即响应，防止超时
        await self.bot.api_scheduler.submit(safeDefer(interaction, ephemeral=True), 1)

        # 基本校验
        if not interaction.message:
            await self.bot.api_scheduler.submit(
                interaction.followup.send("无法找到投票面板消息，请重试。", ephemeral=True), 1
            )
            return

        # 分派事件
        logger.debug(
            (
                "分派异议创建投票事件: "
                f"user={interaction.user.id}, choice={choice}, message={interaction.message.id}"
            )
        )
        self.bot.dispatch("objection_creation_vote_cast", interaction, choice)
