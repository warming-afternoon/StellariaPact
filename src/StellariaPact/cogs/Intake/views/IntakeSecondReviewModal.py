from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ui import Label, Modal, TextInput

if TYPE_CHECKING:
    from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


class IntakeSecondReviewModal(Modal):
    """二审批准 Modal —— 展示第一位管理审核意见，收集第二位管理的意见。"""

    def __init__(
        self,
        bot: "StellariaPactBot",
        first_reviewer_id: int,
        first_review_comment: str,
    ):
        super().__init__(title="二审批准 - 审核确认")
        self.bot = bot

        # 展示第一位管理审核意见的只读 TextInput（被 Label 包裹）
        self.first_comment_display = TextInput(
            label="第一位管理的审核意见",
            default=first_review_comment,
            required=False,
            style=discord.TextStyle.paragraph,
        )

        self.add_item(
            Label(
                text="📋 第一位管理的审核意见（参考）",
                description=f"审核人: <@{first_reviewer_id}>",
                component=self.first_comment_display,
            )
        )

        # 第二位管理的审核意见输入框
        self.second_comment_input = TextInput(
            label="你的审核意见",
            style=discord.TextStyle.paragraph,
            placeholder="请填写你的审核意见...",
            required=True,
            max_length=2000,
        )
        self.add_item(self.second_comment_input)

    async def on_submit(self, interaction: discord.Interaction):
        # 从 children 中获取 Label，再从中提取 TextInput 的值
        # children[0] = Label, children[1] = second_comment_input
        review_comment = self.second_comment_input.value

        logger.info(
            f"二审批准 Modal 提交，审核人: {interaction.user.id}, "
            f"审核意见: {review_comment[:50]}..."
        )

        await interaction.response.defer(ephemeral=True)

        # 分发事件，传入第二位管理的意见
        self.bot.dispatch("intake_approved", interaction, review_comment)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        logger.error(f"二审批准 Modal 发生错误 {interaction.user.id}: {error}")
        await interaction.response.defer(ephemeral=True) if not interaction.response.is_done() else None
        error_msg = f"处理二审批准时发生错误，请稍后再试。\n{error}"
        await interaction.followup.send(error_msg, ephemeral=True)
