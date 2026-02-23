from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ui import Button, View

from StellariaPact.cogs.Intake.views.IntakeReviewModal import IntakeReviewModal
from StellariaPact.share.auth.RoleGuard import RoleGuard

if TYPE_CHECKING:
    from StellariaPact.share.StellariaPactBot import StellariaPactBot


class IntakeReviewView(View):
    """
    一个用于审核草案的视图，包含"批准"、"拒绝"和"要求修改"按钮。
    """

    def __init__(self, bot: "StellariaPactBot"):
        super().__init__(timeout=None)
        self.bot = bot

    async def _check_permissions(self, interaction: discord.Interaction) -> bool:
        """检查用户是否有审核权限（stewards身份组）"""
        if not RoleGuard.hasRoles(interaction, "stewards"):
            await interaction.response.send_message(
                "❌ 您没有权限执行此操作，需要 steward 身份组。", ephemeral=True
            )
            return False
        return True

    async def _handle_review_action(self, interaction: discord.Interaction, action: str):
        """处理审核动作的通用方法"""
        if not await self._check_permissions(interaction):
            return

        modal = IntakeReviewModal(self.bot, action)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="✅ 批准",
        style=discord.ButtonStyle.success,
        custom_id="persistent:intake_approve",
    )
    async def approve(self, interaction: discord.Interaction, button: Button):
        await self._handle_review_action(interaction, "approved")

    @discord.ui.button(
        label="❌ 拒绝",
        style=discord.ButtonStyle.danger,
        custom_id="persistent:intake_reject",
    )
    async def reject(self, interaction: discord.Interaction, button: Button):
        await self._handle_review_action(interaction, "rejected")

    @discord.ui.button(
        label="📝 要求修改",
        style=discord.ButtonStyle.secondary,
        custom_id="persistent:intake_modify",
    )
    async def modify(self, interaction: discord.Interaction, button: Button):
        await self._handle_review_action(interaction, "modification_requested")
