from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from StellariaPact.cogs.StructuredSpeech import StructuredSpeechCog
from StellariaPact.cogs.StructuredSpeech.constants import (
    STRUCTURED_SPEECH_MAX_ATTACHMENTS, STRUCTURED_SPEECH_MESSAGE_MAX_LENGTH,
    STRUCTURED_SPEECH_MODAL_TIMEOUT_SECONDS,
    STRUCTURED_SPEECH_REPLY_CONTEXT_MENU_NAME)
from StellariaPact.cogs.StructuredSpeech.ProposalSpeechModal import \
    ProposalSpeechModal
from StellariaPact.cogs.StructuredSpeech.StructuredSpeechUserError import \
    StructuredSpeechUserError


def test_structured_speech_commands_are_registered_with_expected_names() -> None:
    """验证模板管理和提案发言两条命令均完成注册。"""
    command_names = {command.name for command in StructuredSpeechCog.__cog_app_commands__}

    assert command_names == {"模板发言模式", "提案发言"}


def test_proposal_speech_modal_declares_timeout_and_multiple_files() -> None:
    """验证 Modal 包含提及说明、三十分钟超时和五附件限制。"""
    modal = ProposalSpeechModal(MagicMock(), thread_id=100, user_id=200)

    assert modal.timeout == STRUCTURED_SPEECH_MODAL_TIMEOUT_SECONDS == 1800
    assert len(modal.children) == 4
    assert isinstance(modal.children[0], discord.ui.TextDisplay)
    assert "<@用户ID>" in modal.children[0].content
    assert STRUCTURED_SPEECH_REPLY_CONTEXT_MENU_NAME in modal.children[0].content
    assert modal.attachment_upload.min_values == 0
    assert modal.attachment_upload.max_values == STRUCTURED_SPEECH_MAX_ATTACHMENTS == 5
    assert modal.body_input.style is discord.TextStyle.paragraph
    assert modal.reason_input.style is discord.TextStyle.paragraph


@pytest.mark.asyncio
async def test_reply_context_menu_registers_and_unloads_with_expected_name() -> None:
    """验证带半角括号的消息右键指令能够注册并在卸载时移除。"""
    bot = MagicMock()
    cog = StructuredSpeechCog(bot)

    assert cog.proposal_speech_reply_context_menu.name == "提案发言(回复)"
    assert cog.proposal_speech_reply_context_menu.type is discord.AppCommandType.message

    cog.cog_load()
    bot.tree.add_command.assert_called_once_with(cog.proposal_speech_reply_context_menu)

    await cog.cog_unload()
    bot.tree.remove_command.assert_called_once_with(
        "提案发言(回复)",
        type=discord.AppCommandType.message,
    )


@pytest.mark.asyncio
async def test_reply_context_menu_opens_modal_with_saved_reference() -> None:
    """验证右键入口通过预检后把源消息链接和原用户 ID 保存到 Modal。"""
    bot = MagicMock()
    cog = StructuredSpeechCog(bot)
    thread = MagicMock(id=100)
    member = MagicMock(id=200)
    interaction = MagicMock()
    interaction.response.send_modal = AsyncMock()
    message = MagicMock(
        id=300,
        webhook_id=400,
        jump_url="https://discord.com/channels/1/100/300",
    )
    message.author.id = 500
    message.author.bot = True
    cog._get_target_thread = MagicMock(return_value=thread)
    cog._get_interaction_member = MagicMock(return_value=member)
    cog._validate_speech_preflight = AsyncMock()
    cog.service.resolve_reference_user_id = AsyncMock(return_value=600)

    await cog.proposal_speech_reply(interaction, message)

    cog._validate_speech_preflight.assert_awaited_once_with(thread, member)
    resolve_qo = cog.service.resolve_reference_user_id.await_args.args[0]
    assert resolve_qo.message_id == 300
    assert resolve_qo.webhook_id == 400
    modal = interaction.response.send_modal.await_args.args[0]
    assert modal.reference_message_url == "https://discord.com/channels/1/100/300"
    assert modal.reference_user_id == 600


@pytest.mark.asyncio
async def test_reply_context_menu_rejects_punished_user_before_modal() -> None:
    """验证受到发言处罚的用户不能通过右键入口打开表单。"""
    bot = MagicMock()
    cog = StructuredSpeechCog(bot)
    interaction = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.send_modal = AsyncMock()
    thread = MagicMock(id=100)
    member = MagicMock(id=200)
    message = MagicMock()
    cog._get_target_thread = MagicMock(return_value=thread)
    cog._get_interaction_member = MagicMock(return_value=member)
    cog._validate_speech_preflight = AsyncMock(
        side_effect=StructuredSpeechUserError("你当前受到提案发言处罚，无法发送消息。")
    )

    await cog.proposal_speech_reply(interaction, message)

    interaction.response.send_modal.assert_not_awaited()
    interaction.response.send_message.assert_awaited_once_with(
        "你当前受到提案发言处罚，无法发送消息。",
        ephemeral=True,
    )


def test_reply_content_uses_fixed_link_mention_and_body_order() -> None:
    """验证模拟引用严格使用源消息、用户提及、正文和理由的固定顺序。"""
    content = StructuredSpeechCog.format_proposal_speech_content(
        body="正文",
        reason="理由",
        reference_message_url="https://discord.com/channels/1/2/3",
        reference_user_id=456,
    )

    assert content == (
        "-# 回复 <@456> 的 [发言](https://discord.com/channels/1/2/3)\n## 正文\n正文\n\n## 理由\n理由"
    )


def test_reply_prefix_is_included_in_message_length_limit() -> None:
    """验证普通发言刚好达到上限时，增加引用前缀会触发长度校验。"""
    base_content = StructuredSpeechCog.format_proposal_speech_content(
        body="x",
        reason="y",
    )
    body = "x" * (STRUCTURED_SPEECH_MESSAGE_MAX_LENGTH - len(base_content) + 1)

    assert (
        len(StructuredSpeechCog.format_proposal_speech_content(body=body, reason="y"))
        == STRUCTURED_SPEECH_MESSAGE_MAX_LENGTH
    )
    with pytest.raises(StructuredSpeechUserError, match="最多允许 2000 个字符"):
        StructuredSpeechCog.format_proposal_speech_content(
            body=body,
            reason="y",
            reference_message_url="https://discord.com/channels/1/2/3",
            reference_user_id=456,
        )


@pytest.mark.asyncio
async def test_reply_submit_does_not_read_source_message_again() -> None:
    """验证提交时直接使用保存的引用上下文，不重新查询可能已删除的源消息。"""
    bot = MagicMock()
    cog = StructuredSpeechCog(bot)
    thread = MagicMock(id=100)
    thread.guild.id = 10
    thread.fetch_message = AsyncMock()
    member = MagicMock(id=200)
    interaction = MagicMock()
    interaction.followup.send = AsyncMock()
    sent = MagicMock(jump_url="https://discord.com/channels/1/100/700")
    cog._get_target_thread = MagicMock(return_value=thread)
    cog._get_interaction_member = MagicMock(return_value=member)
    cog._is_governance_member = MagicMock(return_value=False)
    cog.service.publish = AsyncMock(return_value=sent)

    with patch(
        "StellariaPact.cogs.StructuredSpeech.StructuredSpeechCog.safeDefer",
        new=AsyncMock(),
    ):
        await cog.submit_proposal_speech(
            interaction,
            expected_thread_id=100,
            expected_user_id=200,
            body="正文",
            reason="理由",
            attachments=[],
            reference_message_url="https://discord.com/channels/1/100/300",
            reference_user_id=600,
        )

    thread.fetch_message.assert_not_awaited()
    publish_qo = cog.service.publish.await_args.kwargs["qo"]
    assert publish_qo.content.startswith(
        "-# 回复 <@600> 的 [发言](https://discord.com/channels/1/100/300)\n## 正文"
    )


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
