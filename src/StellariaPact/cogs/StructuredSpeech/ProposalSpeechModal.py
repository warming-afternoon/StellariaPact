from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from .constants import (
    STRUCTURED_SPEECH_FIELD_MAX_LENGTH,
    STRUCTURED_SPEECH_MAX_ATTACHMENTS,
    STRUCTURED_SPEECH_MODAL_TIMEOUT_SECONDS,
)

if TYPE_CHECKING:
    from .StructuredSpeechCog import StructuredSpeechCog

logger = logging.getLogger(__name__)


class ProposalSpeechModal(discord.ui.Modal, title="提案发言"):
    """在一个弹窗中收集多行正文、理由和可选附件。"""

    def __init__(self, cog: "StructuredSpeechCog", *, thread_id: int, user_id: int):
        """初始化绑定原帖子和原用户的发言表单。"""
        super().__init__(timeout=STRUCTURED_SPEECH_MODAL_TIMEOUT_SECONDS)
        self.cog = cog
        self.thread_id = thread_id
        self.user_id = user_id

        # 正文和理由使用 Modal 专用的段落输入组件。
        self.body_input = discord.ui.TextInput(
            style=discord.TextStyle.paragraph,
            placeholder="请输入发言正文，支持换行和 Markdown。",
            required=True,
            min_length=1,
            max_length=STRUCTURED_SPEECH_FIELD_MAX_LENGTH,
        )
        self.reason_input = discord.ui.TextInput(
            style=discord.TextStyle.paragraph,
            placeholder="请输入支持该发言的理由，支持换行和 Markdown。",
            required=True,
            min_length=1,
            max_length=STRUCTURED_SPEECH_FIELD_MAX_LENGTH,
        )
        # 附件为可选项，并在组件层直接限制最多五个文件。
        self.attachment_upload = discord.ui.FileUpload(
            required=False,
            min_values=0,
            max_values=STRUCTURED_SPEECH_MAX_ATTACHMENTS,
        )

        # Discord 要求新式 Modal 输入组件放在 Label 中。
        self.add_item(
            discord.ui.Label(
                text="正文",
                description="必填，最多 1800 个字符。",
                component=self.body_input,
            )
        )
        self.add_item(
            discord.ui.Label(
                text="理由",
                description="必填，最多 1800 个字符。",
                component=self.reason_input,
            )
        )
        self.add_item(
            discord.ui.Label(
                text="附件（可选）",
                description="最多上传 5 个文件。",
                component=self.attachment_upload,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """把表单值交给控制器执行二次校验和发送。"""
        await self.cog.submit_proposal_speech(
            interaction,
            expected_thread_id=self.thread_id,
            expected_user_id=self.user_id,
            body=self.body_input.value,
            reason=self.reason_input.value,
            attachments=list(self.attachment_upload.values),
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        """捕获未处理表单异常并向提交者返回私密提示。"""
        logger.exception(
            "提案发言表单发生未处理异常。",
            exc_info=(type(error), error, error.__traceback__),
        )
        message = "处理提案发言表单时发生错误，请稍后重试。"
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
