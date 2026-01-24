from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ui import Button, View

if TYPE_CHECKING:
    from StellariaPact.share.StellariaPactBot import StellariaPactBot


class IntakeReviewView(View):
    """
    一个用于审核草案的视图，包含“批准”、“拒绝”和“要求修改”按钮。
    """

    def __init__(self, bot: "StellariaPactBot", intake_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.intake_id = intake_id

    @discord.ui.button(
        label="✅ 批准",
        style=discord.ButtonStyle.success,
        custom_id="persistent:intake_approve",
    )
    async def approve(self, interaction: discord.Interaction, button: Button):
        self.bot.dispatch("intake_approved", self.intake_id)
        await interaction.response.send_message(
            f"✅ 草案 `{self.intake_id}` 已批准，正在创建支持票收集贴...", ephemeral=True
        )
        button.disabled = True
        assert interaction.message is not None
        await interaction.message.edit(view=self)

    @discord.ui.button(
        label="❌ 拒绝",
        style=discord.ButtonStyle.danger,
        custom_id="persistent:intake_reject",
    )
    async def reject(self, interaction: discord.Interaction, button: Button):
        self.bot.dispatch("intake_rejected", self.intake_id)
        await interaction.response.send_message(
            f"❌ 草案 `{self.intake_id}` 已被拒绝。", ephemeral=True
        )
        button.disabled = True
        assert interaction.message is not None
        await interaction.message.edit(view=self)

    @discord.ui.button(
        label="📝 要求修改",
        style=discord.ButtonStyle.secondary,
        custom_id="persistent:intake_modify",
    )
    async def modify(self, interaction: discord.Interaction, button: Button):
        self.bot.dispatch("intake_modification_requested", self.intake_id)
        await interaction.response.send_message(
            f"📝 草案 `{self.intake_id}` 已标记为需要修改。", ephemeral=True
        )
        button.disabled = True
        assert interaction.message is not None
        await interaction.message.edit(view=self)
