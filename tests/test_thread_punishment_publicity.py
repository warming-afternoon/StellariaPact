from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from StellariaPact.cogs.Punishment.dto import ThreadPunishmentResult
from StellariaPact.cogs.Punishment.views.PunishmentModal import (
    MAX_PUNISHMENT_EVIDENCE_FILES,
    PunishmentModal,
)


async def _submit_immediately(coroutine, priority):
    del priority
    return await coroutine


def _create_modal():
    bot = MagicMock()
    bot.api_scheduler.submit.side_effect = _submit_immediately
    target_user = MagicMock(id=50, mention="<@50>")
    target_message = MagicMock(
        jump_url="https://discord.com/channels/10/30/100",
    )
    target_message.forward = AsyncMock(return_value=MagicMock())
    modal = PunishmentModal(bot, target_user, target_message)
    modal.allow_voting_input._value = "否"
    modal.mute_duration_input._value = "60"
    modal.reason_input._value = "测试处罚"
    return modal, bot, target_message


def _create_interaction():
    guild = MagicMock(id=10)
    thread = MagicMock(id=30, guild=guild)
    moderator = MagicMock(id=40, mention="<@40>")
    interaction = MagicMock(channel=thread, user=moderator)
    interaction.followup.send = AsyncMock()
    return interaction, thread, moderator


def test_punishment_modal_accepts_up_to_five_optional_files() -> None:
    modal, _, _ = _create_modal()

    assert modal.evidence_upload.required is False
    assert modal.evidence_upload.min_values == 0
    assert modal.evidence_upload.max_values == MAX_PUNISHMENT_EVIDENCE_FILES == 5
    assert isinstance(modal.children[-1], discord.ui.Label)


@pytest.mark.asyncio
async def test_configured_publicity_sends_files_then_source_link() -> None:
    modal, _, target_message = _create_modal()
    interaction, thread, moderator = _create_interaction()
    publicity_channel = MagicMock(id=99)
    delivery_order: list[str] = []
    public_message = MagicMock(
        id=200,
        jump_url="https://discord.com/channels/10/99/200",
    )

    async def send_publicity(**kwargs):
        del kwargs
        delivery_order.append("publicity")
        return public_message

    async def forward_evidence(destination):
        del destination
        delivery_order.append("evidence")
        return MagicMock()

    publicity_channel.send = AsyncMock(side_effect=send_publicity)
    target_message.forward.side_effect = forward_evidence
    thread.send = AsyncMock(return_value=MagicMock())
    file = MagicMock(spec=discord.File)
    attachment = MagicMock()
    attachment.to_file = AsyncMock(return_value=file)
    modal.evidence_upload._values = [attachment]
    modal._get_publicity_channel = AsyncMock(return_value=(publicity_channel, None))
    modal.logic.apply_thread_punishment = AsyncMock(
        return_value=ThreadPunishmentResult(7, [])
    )
    modal.logic.set_thread_punishment_publicity_message = AsyncMock()

    with (
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Thread",
            type(thread),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Member",
            type(moderator),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.safeDefer",
            new=AsyncMock(),
        ),
    ):
        await modal.on_submit(interaction)

    attachment.to_file.assert_awaited_once_with()
    public_kwargs = publicity_channel.send.await_args.kwargs
    assert public_kwargs["files"] == [file]
    public_embed = public_kwargs["embed"]
    assert {field.name for field in public_embed.fields}.isdisjoint({"触发消息", "处罚公示"})
    source_kwargs = thread.send.await_args.kwargs
    assert "files" not in source_kwargs
    source_embed = source_kwargs["embed"]
    publicity_field = next(field for field in source_embed.fields if field.name == "处罚公示")
    assert public_message.jump_url in publicity_field.value
    modal.logic.set_thread_punishment_publicity_message.assert_awaited_once_with(
        7,
        guild_id=10,
        channel_id=99,
        message_id=200,
    )
    target_message.forward.assert_awaited_once_with(publicity_channel)
    assert delivery_order == ["publicity", "evidence"]
    file.close.assert_called_once_with()
    interaction.followup.send.assert_awaited_once_with(
        "已成功处罚并完成双区公示。",
        ephemeral=True,
    )


@pytest.mark.asyncio
async def test_missing_publicity_config_falls_back_without_reading_files() -> None:
    modal, _, target_message = _create_modal()
    interaction, thread, moderator = _create_interaction()
    thread.send = AsyncMock(return_value=MagicMock())
    attachment = MagicMock()
    attachment.to_file = AsyncMock()
    modal.evidence_upload._values = [attachment]
    modal._get_publicity_channel = AsyncMock(return_value=(None, "未配置处罚公示区"))
    modal.logic.apply_thread_punishment = AsyncMock(
        return_value=ThreadPunishmentResult(7, [])
    )

    with (
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Thread",
            type(thread),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Member",
            type(moderator),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.safeDefer",
            new=AsyncMock(),
        ),
    ):
        await modal.on_submit(interaction)

    attachment.to_file.assert_not_awaited()
    target_message.forward.assert_not_awaited()
    fallback_embed = thread.send.await_args.kwargs["embed"]
    trigger_field = next(field for field in fallback_embed.fields if field.name == "触发消息")
    assert target_message.jump_url in trigger_field.value
    response = interaction.followup.send.await_args.args[0]
    assert "降级为原帖单处公示" in response
    assert "上传的处罚材料未发布" in response


@pytest.mark.asyncio
async def test_runtime_publicity_failure_keeps_punishment_and_suppresses_source_notice() -> None:
    modal, _, target_message = _create_modal()
    interaction, thread, moderator = _create_interaction()
    publicity_channel = MagicMock(id=99)
    publicity_channel.send = AsyncMock(side_effect=RuntimeError("Discord unavailable"))
    thread.send = AsyncMock()
    file = MagicMock(spec=discord.File)
    attachment = MagicMock()
    attachment.to_file = AsyncMock(return_value=file)
    modal.evidence_upload._values = [attachment]
    modal._get_publicity_channel = AsyncMock(return_value=(publicity_channel, None))
    modal.logic.apply_thread_punishment = AsyncMock(
        return_value=ThreadPunishmentResult(7, [])
    )

    with (
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Thread",
            type(thread),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Member",
            type(moderator),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.safeDefer",
            new=AsyncMock(),
        ),
    ):
        await modal.on_submit(interaction)

    modal.logic.apply_thread_punishment.assert_awaited_once()
    target_message.forward.assert_not_awaited()
    thread.send.assert_not_awaited()
    file.close.assert_called_once_with()
    response = interaction.followup.send.await_args.args[0]
    assert "处罚已生效" in response
    assert "原帖未发布无效跳转链接" in response


@pytest.mark.asyncio
async def test_evidence_forward_failure_keeps_publicity_and_reports_warning() -> None:
    modal, _, target_message = _create_modal()
    interaction, thread, moderator = _create_interaction()
    publicity_channel = MagicMock(id=99)
    public_message = MagicMock(
        id=200,
        jump_url="https://discord.com/channels/10/99/200",
    )
    publicity_channel.send = AsyncMock(return_value=public_message)
    target_message.forward.side_effect = RuntimeError("cannot forward")
    thread.send = AsyncMock(return_value=MagicMock())
    modal.evidence_upload._values = []
    modal._get_publicity_channel = AsyncMock(return_value=(publicity_channel, None))
    modal.logic.apply_thread_punishment = AsyncMock(
        return_value=ThreadPunishmentResult(7, [])
    )
    modal.logic.set_thread_punishment_publicity_message = AsyncMock()

    with (
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Thread",
            type(thread),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Member",
            type(moderator),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.safeDefer",
            new=AsyncMock(),
        ),
    ):
        await modal.on_submit(interaction)

    target_message.forward.assert_awaited_once_with(publicity_channel)
    modal.logic.set_thread_punishment_publicity_message.assert_awaited_once_with(
        7,
        guild_id=10,
        channel_id=99,
        message_id=200,
    )
    thread.send.assert_awaited_once()
    source_embed = thread.send.await_args.kwargs["embed"]
    publicity_field = next(
        field for field in source_embed.fields if field.name == "处罚公示"
    )
    assert public_message.jump_url in publicity_field.value
    response = interaction.followup.send.await_args.args[0]
    assert "处罚已生效，正式公示已发送" in response
    assert "选中消息转发失败，请人工补发" in response


@pytest.mark.asyncio
async def test_publicity_without_target_message_does_not_attempt_forward() -> None:
    modal, _, target_message = _create_modal()
    modal.target_message = None
    interaction, thread, moderator = _create_interaction()
    publicity_channel = MagicMock(id=99)
    public_message = MagicMock(
        id=200,
        jump_url="https://discord.com/channels/10/99/200",
    )
    publicity_channel.send = AsyncMock(return_value=public_message)
    thread.send = AsyncMock(return_value=MagicMock())
    modal.evidence_upload._values = []
    modal._get_publicity_channel = AsyncMock(return_value=(publicity_channel, None))
    modal.logic.apply_thread_punishment = AsyncMock(
        return_value=ThreadPunishmentResult(7, [])
    )
    modal.logic.set_thread_punishment_publicity_message = AsyncMock()

    with (
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Thread",
            type(thread),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Member",
            type(moderator),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.safeDefer",
            new=AsyncMock(),
        ),
    ):
        await modal.on_submit(interaction)

    publicity_channel.send.assert_awaited_once()
    target_message.forward.assert_not_awaited()
    interaction.followup.send.assert_awaited_once_with(
        "已成功处罚并完成双区公示。",
        ephemeral=True,
    )


@pytest.mark.asyncio
async def test_attachment_read_failure_happens_before_punishment() -> None:
    modal, _, _ = _create_modal()
    interaction, thread, moderator = _create_interaction()
    publicity_channel = MagicMock(id=99)
    attachment = MagicMock()
    attachment.to_file = AsyncMock(side_effect=RuntimeError("attachment unavailable"))
    modal.evidence_upload._values = [attachment]
    modal._get_publicity_channel = AsyncMock(return_value=(publicity_channel, None))
    modal.logic.apply_thread_punishment = AsyncMock()

    with (
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Thread",
            type(thread),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Member",
            type(moderator),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.safeDefer",
            new=AsyncMock(),
        ),
    ):
        await modal.on_submit(interaction)

    modal.logic.apply_thread_punishment.assert_not_awaited()
    interaction.followup.send.assert_awaited_once_with(
        "处理请求时发生错误，请联系技术人员。",
        ephemeral=True,
    )


@pytest.mark.asyncio
async def test_location_writeback_failure_still_sends_source_with_direct_link() -> None:
    modal, _, _ = _create_modal()
    interaction, thread, moderator = _create_interaction()
    publicity_channel = MagicMock(id=99)
    public_message = MagicMock(
        id=200,
        jump_url="https://discord.com/channels/10/99/200",
    )
    publicity_channel.send = AsyncMock(return_value=public_message)
    thread.send = AsyncMock(return_value=MagicMock())
    modal.evidence_upload._values = []
    modal._get_publicity_channel = AsyncMock(return_value=(publicity_channel, None))
    modal.logic.apply_thread_punishment = AsyncMock(
        return_value=ThreadPunishmentResult(7, [])
    )
    modal.logic.set_thread_punishment_publicity_message = AsyncMock(
        side_effect=RuntimeError("database unavailable")
    )

    with (
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Thread",
            type(thread),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Member",
            type(moderator),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.safeDefer",
            new=AsyncMock(),
        ),
    ):
        await modal.on_submit(interaction)

    source_embed = thread.send.await_args.kwargs["embed"]
    publicity_field = next(field for field in source_embed.fields if field.name == "处罚公示")
    assert public_message.jump_url in publicity_field.value
    response = interaction.followup.send.await_args.args[0]
    assert "历史记录未能保存正式公示链接" in response


@pytest.mark.asyncio
async def test_source_notice_failure_preserves_publicity_and_reports_partial_failure() -> None:
    modal, _, _ = _create_modal()
    interaction, thread, moderator = _create_interaction()
    publicity_channel = MagicMock(id=99)
    public_message = MagicMock(
        id=200,
        jump_url="https://discord.com/channels/10/99/200",
    )
    publicity_channel.send = AsyncMock(return_value=public_message)
    thread.send = AsyncMock(side_effect=RuntimeError("thread unavailable"))
    modal.evidence_upload._values = []
    modal._get_publicity_channel = AsyncMock(return_value=(publicity_channel, None))
    modal.logic.apply_thread_punishment = AsyncMock(
        return_value=ThreadPunishmentResult(7, [])
    )
    modal.logic.set_thread_punishment_publicity_message = AsyncMock()

    with (
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Thread",
            type(thread),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Member",
            type(moderator),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.safeDefer",
            new=AsyncMock(),
        ),
    ):
        await modal.on_submit(interaction)

    publicity_channel.send.assert_awaited_once()
    modal.logic.set_thread_punishment_publicity_message.assert_awaited_once()
    response = interaction.followup.send.await_args.args[0]
    assert "原帖公示发送失败" in response


@pytest.mark.asyncio
async def test_publicity_channel_validation_requires_text_channel_and_permissions() -> None:
    modal, bot, _ = _create_modal()
    guild = MagicMock()
    thread = MagicMock(guild=guild)

    bot.config = {"channels": {"punishment_publicity": None}}
    assert await modal._get_publicity_channel(thread) == (None, "未配置处罚公示区")

    channel = MagicMock()
    guild.get_channel_or_thread.return_value = channel
    bot.config = {"channels": {"punishment_publicity": 99}}
    permissions = SimpleNamespace(
        view_channel=True,
        send_messages=True,
        embed_links=True,
        attach_files=False,
    )
    channel.permissions_for.return_value = permissions
    guild.me = MagicMock()
    with patch(
        "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.TextChannel",
        type(channel),
    ):
        resolved, reason = await modal._get_publicity_channel(thread)

    assert resolved is None
    assert "上传附件" in reason


@pytest.mark.asyncio
async def test_archived_publicity_thread_is_fetched_and_uses_thread_permissions() -> None:
    modal, bot, _ = _create_modal()
    guild = MagicMock()
    source_thread = MagicMock(guild=guild)
    publicity_thread = MagicMock(archived=True, locked=False)
    permissions = SimpleNamespace(
        view_channel=True,
        send_messages_in_threads=True,
        embed_links=True,
        attach_files=True,
        manage_threads=False,
    )
    publicity_thread.permissions_for.return_value = permissions
    guild.me = MagicMock()
    guild.get_channel_or_thread.return_value = None
    guild.fetch_channel = AsyncMock(return_value=publicity_thread)
    bot.config = {"channels": {"punishment_publicity": 99}}

    with patch(
        "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Thread",
        type(publicity_thread),
    ):
        resolved, reason = await modal._get_publicity_channel(source_thread)

    assert resolved is publicity_thread
    assert reason is None
    guild.fetch_channel.assert_awaited_once_with(99)


@pytest.mark.asyncio
async def test_locked_publicity_thread_without_manage_permission_falls_back() -> None:
    modal, bot, _ = _create_modal()
    guild = MagicMock()
    source_thread = MagicMock(guild=guild)
    publicity_thread = MagicMock(archived=True, locked=True)
    permissions = SimpleNamespace(
        view_channel=True,
        send_messages_in_threads=True,
        embed_links=True,
        attach_files=True,
        manage_threads=False,
    )
    publicity_thread.permissions_for.return_value = permissions
    guild.me = MagicMock()
    guild.get_channel_or_thread.return_value = publicity_thread
    bot.config = {"channels": {"punishment_publicity": 99}}

    with patch(
        "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Thread",
        type(publicity_thread),
    ):
        resolved, reason = await modal._get_publicity_channel(source_thread)

    assert resolved is None
    assert reason == "处罚公示子区已锁定且 Bot 无管理子区权限"
    guild.fetch_channel.assert_not_called()


@pytest.mark.asyncio
async def test_locked_publicity_thread_is_unlocked_and_left_active_after_success() -> None:
    modal, _, target_message = _create_modal()
    interaction, source_thread, moderator = _create_interaction()
    publicity_thread = MagicMock(id=99, archived=True, locked=True)
    public_message = MagicMock(
        id=200,
        jump_url="https://discord.com/channels/10/99/200",
    )
    publicity_thread.edit = AsyncMock(return_value=publicity_thread)
    publicity_thread.send = AsyncMock(return_value=public_message)
    source_thread.send = AsyncMock(return_value=MagicMock())
    modal.evidence_upload._values = []
    modal._get_publicity_channel = AsyncMock(return_value=(publicity_thread, None))
    modal.logic.apply_thread_punishment = AsyncMock(
        return_value=ThreadPunishmentResult(7, [])
    )
    modal.logic.set_thread_punishment_publicity_message = AsyncMock()

    with (
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Thread",
            (type(source_thread), type(publicity_thread)),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Member",
            type(moderator),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.safeDefer",
            new=AsyncMock(),
        ),
    ):
        await modal.on_submit(interaction)

    publicity_thread.edit.assert_awaited_once_with(
        locked=False,
        archived=False,
        reason="发送帖子内处罚正式公示",
    )
    publicity_thread.send.assert_awaited_once()
    target_message.forward.assert_awaited_once_with(publicity_thread)
    source_thread.send.assert_awaited_once()


@pytest.mark.asyncio
async def test_publicity_thread_unlock_failure_keeps_punishment_and_closes_files() -> None:
    modal, _, _ = _create_modal()
    interaction, source_thread, moderator = _create_interaction()
    publicity_thread = MagicMock(id=99, archived=True, locked=True)
    publicity_thread.edit = AsyncMock(side_effect=RuntimeError("cannot unlock"))
    publicity_thread.send = AsyncMock()
    source_thread.send = AsyncMock()
    file = MagicMock(spec=discord.File)
    attachment = MagicMock()
    attachment.to_file = AsyncMock(return_value=file)
    modal.evidence_upload._values = [attachment]
    modal._get_publicity_channel = AsyncMock(return_value=(publicity_thread, None))
    modal.logic.apply_thread_punishment = AsyncMock(
        return_value=ThreadPunishmentResult(7, [])
    )

    with (
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Thread",
            (type(source_thread), type(publicity_thread)),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Member",
            type(moderator),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.safeDefer",
            new=AsyncMock(),
        ),
    ):
        await modal.on_submit(interaction)

    modal.logic.apply_thread_punishment.assert_awaited_once()
    publicity_thread.send.assert_not_awaited()
    source_thread.send.assert_not_awaited()
    file.close.assert_called_once_with()
    response = interaction.followup.send.await_args.args[0]
    assert "自动解锁失败" in response


@pytest.mark.asyncio
@pytest.mark.parametrize("restore_succeeds", [True, False])
async def test_send_failure_after_unlock_attempts_to_restore_original_state(
    restore_succeeds: bool,
) -> None:
    modal, _, _ = _create_modal()
    interaction, source_thread, moderator = _create_interaction()
    publicity_thread = MagicMock(id=99, archived=True, locked=True)
    restore_result = publicity_thread if restore_succeeds else RuntimeError("cannot restore")
    publicity_thread.edit = AsyncMock(side_effect=[publicity_thread, restore_result])
    publicity_thread.send = AsyncMock(side_effect=RuntimeError("cannot send"))
    source_thread.send = AsyncMock()
    modal.evidence_upload._values = []
    modal._get_publicity_channel = AsyncMock(return_value=(publicity_thread, None))
    modal.logic.apply_thread_punishment = AsyncMock(
        return_value=ThreadPunishmentResult(7, [])
    )

    with (
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Thread",
            (type(source_thread), type(publicity_thread)),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.discord.Member",
            type(moderator),
        ),
        patch(
            "StellariaPact.cogs.Punishment.views.PunishmentModal.safeDefer",
            new=AsyncMock(),
        ),
    ):
        await modal.on_submit(interaction)

    assert publicity_thread.edit.await_count == 2
    assert publicity_thread.edit.await_args_list[1].kwargs == {
        "locked": True,
        "archived": True,
        "reason": "处罚公示发送失败，恢复子区原状态",
    }
    source_thread.send.assert_not_awaited()
    response = interaction.followup.send.await_args.args[0]
    if restore_succeeds:
        assert "已恢复原来的锁定和归档状态" in response
    else:
        assert "未能恢复原来的锁定和归档状态" in response
