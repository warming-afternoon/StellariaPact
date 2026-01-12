from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

import discord

from ..dto.UpdateProposalContentDto import UpdateProposalContentDto

if TYPE_CHECKING:
    from StellariaPact.dto.ProposalIntakeDto import ProposalIntakeDto

logger = logging.getLogger(__name__)


class EditProposalContentModal(discord.ui.Modal, title="修改提案内容"):
    """
    用于修改提案内容的模态框。
    允许 stewards 修改提案的标题、原因、动议、执行方案和执行人。
    """

    def __init__(self, proposal_id: int, intake: Optional["ProposalIntakeDto"] = None):
        super().__init__()
        self.proposal_id = proposal_id

        # 若 intake 存在，预填充默认值
        self.title_input.default = intake.title if intake else None
        self.reason_input.default = intake.reason if intake else None
        self.motion_input.default = intake.motion if intake else None
        self.implementation_input.default = intake.implementation if intake else None
        self.executor_input.default = intake.executor if intake else None

    title_input = discord.ui.TextInput(
        label="标题",
        placeholder="请输入提案标题，简洁明了，不超过100字",
        style=discord.TextStyle.short,
        max_length=100,
        required=True,
    )

    reason_input = discord.ui.TextInput(
        label="提案原因",
        placeholder="请详细说明您为什么提出这项动议，以及它试图解决什么问题。",
        style=discord.TextStyle.long,
        max_length=1000,
        required=True,
    )

    motion_input = discord.ui.TextInput(
        label="议案动议",
        placeholder="请陈述您的具体建议。",
        style=discord.TextStyle.long,
        max_length=1000,
        required=True,
    )

    implementation_input = discord.ui.TextInput(
        label="执行方案",
        placeholder="请描述该动议将如何被执行，包括具体步骤、负责人或相关工具。",
        style=discord.TextStyle.long,
        max_length=1000,
        required=True,
    )

    executor_input = discord.ui.TextInput(
        label="执行人",
        placeholder="请指出该议案的主要执行负责人或团队。",
        style=discord.TextStyle.short,
        max_length=100,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        """
        当用户提交表单时被调用。
        触发 proposal_content_update_requested 事件，由 Cog 处理实际更新逻辑。
        """
        
        # 获取当前线程 ID
        thread_id = interaction.channel_id if interaction.channel_id else 0

        dto = UpdateProposalContentDto(
            proposal_id=self.proposal_id,
            title=self.title_input.value,
            reason=self.reason_input.value,
            motion=self.motion_input.value,
            implementation=self.implementation_input.value,
            executor=self.executor_input.value,
            thread_id=thread_id,
        )

        # 触发事件，让 Cog 处理后续逻辑
        interaction.client.dispatch("proposal_content_update_requested", dto, interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        """
        当提交过程中发生错误时被调用。
        """
        logger.error(f"修改提案内容时发生错误: {error}", exc_info=True)
        if not interaction.response.is_done():
            await interaction.response.send_message(
                "❌ 修改提案内容时发生错误，请稍后再试。", ephemeral=True
            )
