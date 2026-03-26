from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ui import Modal, TextInput

from StellariaPact.cogs.Intake.dto.IntakeSubmissionDto import IntakeSubmissionDto
from StellariaPact.share.SafeDefer import safeDefer

if TYPE_CHECKING:
    from StellariaPact.dto.ProposalIntakeDto import ProposalIntakeDto
    from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


class IntakeEditModal(Modal):
    """
    用于提案人修改草案的模态框
    """

    def __init__(self, bot: "StellariaPactBot", intake: "ProposalIntakeDto"):
        super().__init__(title="修改议案草案")
        self.bot = bot
        self.intake_id = intake.id

        self.title_input = TextInput(
            label="标题", default=intake.title, max_length=100, required=True
        )
        self.reason_input = TextInput(
            label="原因",
            style=discord.TextStyle.paragraph,
            default=intake.reason,
            max_length=1000,
            required=True,
        )
        self.motion_input = TextInput(
            label="动议",
            style=discord.TextStyle.paragraph,
            default=intake.motion,
            max_length=1000,
            required=True,
        )
        self.implementation_input = TextInput(
            label="方案",
            style=discord.TextStyle.paragraph,
            default=intake.implementation,
            max_length=1000,
            required=True,
        )
        self.executor_input = TextInput(
            label="执行人", default=intake.executor, max_length=100, required=True
        )

        self.add_item(self.title_input)
        self.add_item(self.reason_input)
        self.add_item(self.motion_input)
        self.add_item(self.implementation_input)
        self.add_item(self.executor_input)

    async def on_submit(self, interaction: discord.Interaction):
        await safeDefer(interaction, ephemeral=True)
        # 组装 DTO
        dto = IntakeSubmissionDto(
            author_id=interaction.user.id,
            guild_id=interaction.guild_id or 0,
            title=self.title_input.value,
            reason=self.reason_input.value,
            motion=self.motion_input.value,
            implementation=self.implementation_input.value,
            executor=self.executor_input.value,
        )

        # 触发修改事件
        self.bot.dispatch("intake_edited", interaction, self.intake_id, dto)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.error(f"提案修改过程中发生错误 {interaction.user.id}: {error}")
        await safeDefer(interaction, ephemeral=True)
        error_msg = f"提交修改时发生错误，请稍后再试。\n{error}"
        await interaction.followup.send(error_msg, ephemeral=True)
