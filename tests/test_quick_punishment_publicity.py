from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from StellariaPact.cogs.Punishment.Cog import PunishmentCog
from StellariaPact.cogs.Punishment.dto.ThreadPunishmentResult import ThreadPunishmentResult


async def _submit_immediately(coroutine, priority):
    """立即执行接口调度任务，以验证解锁、发送和恢复的实际顺序。"""
    del priority
    return await coroutine


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "locked,archived,manage_threads,failure",
    [
        (True, True, True, None),
        (True, False, True, None),
        (False, False, False, None),
        (True, True, False, None),
        (True, True, True, "unlock"),
        (True, True, True, "send"),
        (True, True, True, "restore"),
    ],
)
async def test_quick_punishment_publicity_thread_lifecycle(
    locked: bool,
    archived: bool,
    manage_threads: bool,
    failure: str | None,
) -> None:
    """验证快速处罚保留处罚结果，并按公示子区状态解锁、降级或恢复。"""
    # 使用真实入口和公示服务，仅替换数据库操作与 Discord 网络接口。
    bot = MagicMock()
    bot.config = {"channels": {"punishment_publicity": 99}}
    bot.api_scheduler.submit.side_effect = _submit_immediately
    cog = PunishmentCog(bot)
    cog.logic.apply_thread_punishment = AsyncMock(return_value=ThreadPunishmentResult(7, []))
    cog.logic.set_thread_punishment_publicity_message = AsyncMock()
    target = MagicMock(id=50)
    cog._resolve_message_target = AsyncMock(return_value=target)
    cog._validate_context = AsyncMock(return_value=True)
    source = MagicMock(spec=discord.Thread)
    source.id = 30
    source.guild = MagicMock(id=10)
    source.send = AsyncMock()
    moderator = MagicMock(spec=discord.Member)
    moderator.id = 40
    interaction = MagicMock(channel=source, user=moderator)
    interaction.followup.send = AsyncMock()
    message = MagicMock(jump_url="https://discord.com/channels/10/30/100")
    message.forward = AsyncMock()

    # 模拟解锁返回新子区对象，确保后续发送及失败恢复均使用更新后的对象。
    original = MagicMock(spec=discord.Thread)
    original.id = 99
    original.locked = locked
    original.archived = archived
    original.permissions_for.return_value = discord.Permissions.all()
    original.permissions_for.return_value.manage_threads = manage_threads
    source.guild.get_channel_or_thread.return_value = original
    updated = MagicMock(spec=discord.Thread)
    updated.id = 99
    updated.locked = False
    updated.archived = False
    public_message = MagicMock(id=200, jump_url="https://discord.com/channels/10/99/200")
    events = []

    async def unlock(**kwargs):
        """记录解锁操作并模拟权限异常。"""
        events.append("unlock")
        assert kwargs == {
            "locked": False,
            "archived": False,
            "reason": "发送帖子内处罚正式公示",
        }
        if failure == "unlock":
            raise RuntimeError("cannot unlock")
        return updated

    async def send(**kwargs):
        """记录正式公示发送并模拟发送失败。"""
        events.append("send")
        if failure in ("send", "restore"):
            raise RuntimeError("cannot send")
        return public_message

    async def restore(**kwargs):
        """验证失败恢复使用解锁前的归档和锁定状态。"""
        events.append("restore")
        assert kwargs == {
            "locked": locked,
            "archived": archived,
            "reason": "处罚公示发送失败，恢复子区原状态",
        }
        if failure == "restore":
            raise RuntimeError("cannot restore")
        return original

    original.edit = AsyncMock(side_effect=unlock)
    original.send = AsyncMock(side_effect=send)
    updated.send = AsyncMock(side_effect=send)
    updated.edit = AsyncMock(side_effect=restore)

    # 跳过独立测试覆盖的角色装饰器，保留快速处罚到公示服务的完整调用链。
    with (
        patch("StellariaPact.cogs.Punishment.Cog.safeDefer", new=AsyncMock()),
        patch(
            "StellariaPact.cogs.Punishment.Cog.PunishmentEmbedBuilder.create_punishment_embed",
            return_value=discord.Embed(),
        ),
    ):
        await cog.quick_punish_off_topic_message.__wrapped__(cog, interaction, message)

    # 公示异常不回滚已经写入的处罚，也不发送无效的原帖跳转链接。
    cog.logic.apply_thread_punishment.assert_awaited_once()
    bot.dispatch.assert_any_call(
        "thread_mute_updated",
        source.id,
        target.id,
        cog.logic.apply_thread_punishment.await_args.kwargs["mute_end_time"],
    )
    response = interaction.followup.send.await_args.args[0]
    if locked and not manage_threads:
        assert events == []
        assert "降级为原帖单处公示" in response
        source.send.assert_awaited_once()
        message.forward.assert_not_awaited()
        cog.logic.set_thread_punishment_publicity_message.assert_not_awaited()
    elif failure:
        assert events == (["unlock"] if failure == "unlock" else ["unlock", "send", "restore"])
        expected = {
            "unlock": "自动解锁失败",
            "send": "已恢复原来的锁定和归档状态",
            "restore": "未能恢复原来的锁定和归档状态",
        }
        assert expected[failure] in response
        source.send.assert_not_awaited()
        message.forward.assert_not_awaited()
        cog.logic.set_thread_punishment_publicity_message.assert_not_awaited()
    else:
        assert events == (["unlock", "send"] if locked else ["send"])
        message.forward.assert_awaited_once_with(updated if locked else original)
        source.send.assert_awaited_once()
        cog.logic.set_thread_punishment_publicity_message.assert_awaited_once_with(
            7, guild_id=10, channel_id=99, message_id=200
        )
        assert "完成双区公示" in response
