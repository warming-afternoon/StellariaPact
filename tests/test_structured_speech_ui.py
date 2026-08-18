from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import discord

from StellariaPact.cogs.StructuredSpeech import StructuredSpeechCog
from StellariaPact.cogs.StructuredSpeech.constants import (
    STRUCTURED_SPEECH_MAX_ATTACHMENTS,
    STRUCTURED_SPEECH_MODAL_TIMEOUT_SECONDS,
)
from StellariaPact.cogs.StructuredSpeech.ProposalSpeechModal import ProposalSpeechModal


def test_structured_speech_commands_are_registered_with_expected_names() -> None:
    """验证模板管理和提案发言两条命令均完成注册。"""
    command_names = {command.name for command in StructuredSpeechCog.__cog_app_commands__}

    assert command_names == {"模板发言模式", "提案发言"}


def test_proposal_speech_modal_declares_timeout_and_multiple_files() -> None:
    """验证 Modal 集中使用三十分钟超时和五附件限制。"""
    modal = ProposalSpeechModal(MagicMock(), thread_id=100, user_id=200)

    assert modal.timeout == STRUCTURED_SPEECH_MODAL_TIMEOUT_SECONDS == 1800
    assert len(modal.children) == 3
    assert modal.attachment_upload.min_values == 0
    assert modal.attachment_upload.max_values == STRUCTURED_SPEECH_MAX_ATTACHMENTS == 5
    assert modal.body_input.style is discord.TextStyle.paragraph
    assert modal.reason_input.style is discord.TextStyle.paragraph


def test_enable_permission_check_reports_thread_and_forum_permissions() -> None:
    """验证开启前会分别检查帖子权限和父论坛 Webhook 权限。"""
    thread_permissions = SimpleNamespace(
        view_channel=True,
        send_messages_in_threads=True,
        manage_messages=False,
        manage_threads=True,
        attach_files=False,
        read_message_history=True,
    )
    forum_permissions = SimpleNamespace(manage_webhooks=False)
    parent = MagicMock()
    parent.permissions_for.return_value = forum_permissions
    thread = MagicMock()
    thread.parent = parent
    thread.permissions_for.return_value = thread_permissions

    # 测试替换只用于满足运行时类型判断，权限值仍来自独立模拟对象。
    with patch(
        "StellariaPact.cogs.StructuredSpeech.StructuredSpeechCog.discord.ForumChannel",
        type(parent),
    ):
        missing = StructuredSpeechCog.get_missing_enable_permissions(
            thread,
            MagicMock(),
        )

    assert missing == ["管理消息", "上传附件", "管理 Webhook"]
