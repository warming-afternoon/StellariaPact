from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ui import Button, View

from StellariaPact.share.SafeDefer import safeDefer

if TYPE_CHECKING:
    pass


class IntakeSupportView(View):
    """
    一个用于收集草案支持票的视图。
    """

    def __init__(self, intake_id: int):
        super().__init__(timeout=None)
        self.intake_id = intake_id

    @discord.ui.button(
        label="支持提案",
        style=discord.ButtonStyle.success,
        custom_id="persistent:intake_support",
    )
    async def support(self, interaction: discord.Interaction, button: Button):
        """
        处理用户点击“支持”按钮的事件。
        """
        await safeDefer(interaction, ephemeral=True)

        interaction.client.dispatch("intake_support_vote_added", interaction, self.intake_id)
