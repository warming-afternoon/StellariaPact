from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from StellariaPact.cogs.Punishment.Cog import PunishmentCog


async def _submit_immediately(coroutine=None, priority=None, *, coro=None):
    """立即等待测试中的 Discord API 调度任务。"""
    del priority
    return await (coroutine if coroutine is not None else coro)


def _create_cog() -> tuple[PunishmentCog, MagicMock]:
    """创建带即时 API 调度器的处罚控制器。"""
    bot = MagicMock()
    bot.api_scheduler.submit.side_effect = _submit_immediately
    return PunishmentCog(bot), bot


@pytest.mark.asyncio
async def test_structured_message_target_falls_back_to_departed_discord_user() -> None:
    """验证原发言者离群后仍能按真实 Discord 用户 ID 执行操作。"""
    cog, bot = _create_cog()
    cog.message_target_resolver.resolve_user_id = AsyncMock(return_value=600)
    departed_user = MagicMock(id=600, bot=False)
    bot.get_user.return_value = None
    bot.fetch_user = AsyncMock(return_value=departed_user)
    guild = MagicMock()
    guild.get_member.return_value = None
    response = MagicMock(status=404, reason="Not Found")
    guild.fetch_member = AsyncMock(
        side_effect=discord.NotFound(response=response, message="Unknown Member")
    )
    interaction = MagicMock(guild=guild)
    message = MagicMock(id=300, webhook_id=400)
    message.author.id = 400
    message.author.bot = True

    result = await cog._resolve_message_target(interaction, message)

    assert result is departed_user
    bot.fetch_user.assert_awaited_once_with(600)


@pytest.mark.asyncio
async def test_message_punishment_commands_use_resolved_real_user() -> None:
    """验证处罚、解除和历史查询均使用结构化消息对应的真实用户。"""
    cog, bot = _create_cog()
    real_user = MagicMock(id=600, bot=False)
    message = MagicMock(id=300, webhook_id=400)
    message.jump_url = "https://discord.com/channels/1/100/300"
    thread = MagicMock(id=100)
    interaction = MagicMock(channel=thread)
    interaction.response.send_modal = AsyncMock()
    cog._resolve_message_target = AsyncMock(return_value=real_user)
    cog._validate_context = AsyncMock(return_value=True)

    # 绕过角色装饰器，直接验证三个右键入口的业务目标传递。
    await cog.kick_proposal_message.__wrapped__(cog, interaction, message)
    punishment_modal = interaction.response.send_modal.await_args.args[0]
    assert punishment_modal.target_user is real_user
    assert punishment_modal.target_message is message

    interaction.response.send_modal.reset_mock()
    await cog.remove_punishment_message.__wrapped__(cog, interaction, message)
    removal_modal = interaction.response.send_modal.await_args.args[0]
    assert removal_modal.target_user is real_user

    punishment_record_repository = SimpleNamespace(
        get_summary=AsyncMock(return_value=(0, [])),
    )
    fake_uow = SimpleNamespace(punishment_record=punishment_record_repository)

    class UnitOfWorkContext:
        """为处罚历史查询提供测试工作单元。"""

        async def __aenter__(self):
            """返回测试工作单元。"""
            return fake_uow

        async def __aexit__(self, exc_type, exc_value, traceback):
            """结束测试工作单元上下文。"""
            return False

    interaction.response.send_modal.reset_mock()
    with (
        patch(
            "StellariaPact.cogs.Punishment.Cog.discord.Thread",
            type(thread),
        ),
        patch(
            "StellariaPact.cogs.Punishment.Cog.UnitOfWork",
            return_value=UnitOfWorkContext(),
        ),
    ):
        await cog.query_punishment_message.__wrapped__(cog, interaction, message)

    punishment_record_repository.get_summary.assert_awaited_once_with(
        thread_id=100,
        target_user_id=600,
    )
    history_modal = interaction.response.send_modal.await_args.args[0]
    assert history_modal.children[0].content.startswith(f"👤 用户：{real_user.mention}")
    assert cog._resolve_message_target.await_count == 3
    assert bot.api_scheduler.submit.call_count == 3


@pytest.mark.asyncio
async def test_resolved_self_target_is_rejected() -> None:
    """验证结构化消息还原后的真实用户仍受禁止处罚自己的规则约束。"""
    cog, _ = _create_cog()
    target_user = MagicMock(id=600, bot=False)
    interaction = MagicMock()
    interaction.user.id = 600
    interaction.response.send_message = AsyncMock()
    thread = MagicMock()
    interaction.channel = thread

    with patch("StellariaPact.cogs.Punishment.Cog.discord.Thread", type(thread)):
        valid = await cog._validate_context(interaction, target_user)

    assert valid is False
    interaction.response.send_message.assert_awaited_once_with(
        "不能对自己执行此操作。",
        ephemeral=True,
    )
