from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from StellariaPact.cogs.StructuredSpeech.StructuredSpeechCog import StructuredSpeechCog


async def submit(coroutine, priority):
    return await coroutine


def setup_message():
    bot = MagicMock()
    bot.api_scheduler.submit.side_effect = submit
    cog = StructuredSpeechCog(bot)
    cog.service.get_active_mode = MagicMock(return_value=object())
    cog._is_target_thread = MagicMock(return_value=True)
    cog._is_governance_member = MagicMock(return_value=False)
    author = MagicMock(spec=discord.Member, id=20, bot=False, mention="<@20>")
    channel = MagicMock(spec=discord.Thread, id=10)
    channel.send = AsyncMock()
    message = MagicMock(
        spec=discord.Message, id=30, author=author, channel=channel, webhook_id=None
    )
    message.delete = AsyncMock()
    return cog, message


@pytest.mark.asyncio
async def test_notice_after_successful_delete_only_mentions_author_and_expires():
    cog, message = setup_message()
    order = []
    message.delete.side_effect = lambda: order.append("delete")
    message.channel.send.side_effect = lambda *args, **kwargs: order.append("notice")
    await cog.on_message(message)
    assert order == ["delete", "notice"]
    kwargs = message.channel.send.await_args.kwargs
    assert kwargs["delete_after"] == 180
    mentions = kwargs["allowed_mentions"]
    assert mentions.users == [message.author]
    assert not mentions.roles and not mentions.everyone and not mentions.replied_user
    assert message.channel.send.await_args.args[0] == (
        "<@20> 本帖已开启模板发言模式，请使用 /提案发言 "
        "或右键消息 → APP → 提案发言(回复)。直接发送的消息已删除。"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [discord.NotFound, discord.Forbidden, discord.HTTPException])
async def test_no_notice_when_delete_fails(failure):
    cog, message = setup_message()
    message.delete.side_effect = failure(MagicMock(status=404, reason="failure"), "删除失败")
    await cog.on_message(message)
    message.channel.send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("exemption", ["bot", "webhook", "governance", "inactive", "other_thread"])
async def test_exempt_messages_are_not_deleted_or_warned(exemption):
    cog, message = setup_message()
    if exemption == "bot":
        message.author.bot = True
    elif exemption == "webhook":
        message.webhook_id = 40
    elif exemption == "governance":
        cog._is_governance_member.return_value = True
    elif exemption == "inactive":
        cog.service.get_active_mode.return_value = None
    else:
        cog._is_target_thread.return_value = False
    await cog.on_message(message)
    message.delete.assert_not_awaited()
    message.channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_notice_failure_does_not_retry_deleted_message():
    cog, message = setup_message()
    message.channel.send.side_effect = discord.Forbidden(
        MagicMock(status=403, reason="failure"), "无权限"
    )
    await cog.on_message(message)
    message.delete.assert_awaited_once()
    message.channel.send.assert_awaited_once()
