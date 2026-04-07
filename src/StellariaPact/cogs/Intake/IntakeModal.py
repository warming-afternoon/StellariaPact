from __future__ import annotations

import logging

import discord

from StellariaPact.share.SafeDefer import safeDefer

from .dto.IntakeSubmissionDto import IntakeSubmissionDto

logger = logging.getLogger(__name__)


class IntakeModal(discord.ui.Modal, title="起草一份新的议案"):
    """
    收集用户提交的新草案。
    """

    def __init__(self, draft: IntakeSubmissionDto | None = None):
        super().__init__()

        self.title_input = discord.ui.TextInput(
            label="标题",
            placeholder="例如：关于调整社区徽章发放标准的提案",
            style=discord.TextStyle.short,
            max_length=100,
            required=True,
            default=draft.title if draft else None,
        )
        self.reason_input = discord.ui.TextInput(
            label="原因",
            placeholder="请详细说明您为什么提出这项动议，以及它试图解决什么问题。",
            style=discord.TextStyle.long,
            max_length=1000,
            required=True,
            default=draft.reason if draft else None,
        )
        self.motion_input = discord.ui.TextInput(
            label="动议",
            placeholder="请陈述您的具体建议。",
            style=discord.TextStyle.long,
            max_length=1000,
            required=True,
            default=draft.motion if draft else None,
        )
        self.implementation_input = discord.ui.TextInput(
            label="方案",
            placeholder="请描述该动议将如何被执行，包括具体步骤、负责人或相关工具。",
            style=discord.TextStyle.long,
            max_length=1000,
            required=True,
            default=draft.implementation if draft else None,
        )
        self.executor_input = discord.ui.TextInput(
            label="执行人",
            placeholder="请指出该议案的主要执行负责人或团队。",
            style=discord.TextStyle.short,
            max_length=100,
            required=True,
            default=draft.executor if draft else None,
        )

        self.add_item(self.title_input)
        self.add_item(self.reason_input)
        self.add_item(self.motion_input)
        self.add_item(self.implementation_input)
        self.add_item(self.executor_input)

    async def on_submit(self, interaction: discord.Interaction):
        """
        当用户提交表单时被调用。
        """
        dto = IntakeSubmissionDto(
            author_id=interaction.user.id,
            guild_id=interaction.guild_id or 0,
            title=self.title_input.value,
            reason=self.reason_input.value,
            motion=self.motion_input.value,
            implementation=self.implementation_input.value,
            executor=self.executor_input.value,
        )

        await safeDefer(interaction, ephemeral=True)
        interaction.client.dispatch("intake_submitted", interaction, dto)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.error(f"提案提交过程中发生错误 {interaction.user.id}: {error}")
        await safeDefer(interaction, ephemeral=True)
        error_msg = f"提交过程中发生错误，请稍后再试。您的草稿已为您保留 30 分钟。\n{error}"
        await interaction.followup.send(error_msg, ephemeral=True)
