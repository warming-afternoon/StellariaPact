from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ui import Button, View

from StellariaPact.share.auth.RoleGuard import RoleGuard
from StellariaPact.share.SafeDefer import safeDefer

if TYPE_CHECKING:
    from StellariaPact.share.StellariaPactBot import StellariaPactBot


class IntakeSupportView(View):
    """
    一个用于收集草案支持票的视图。
    """

    def __init__(self, bot: "StellariaPactBot"):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="支持提案",
        style=discord.ButtonStyle.success,
        custom_id="persistent:intake_support",
    )
    async def support(self, interaction: discord.Interaction, button: Button):
        """
        处理用户点击"支持"按钮的事件。
        """
        if not RoleGuard.hasRoles(interaction, "communityBuilder"):
            await interaction.response.send_message(
                "❌ 抱歉，您没有权限。\n需要「社区建设者」身份组。", ephemeral=True
            )
            return

        await safeDefer(interaction, ephemeral=True)

        self.bot.dispatch("intake_support_vote_added", interaction)
