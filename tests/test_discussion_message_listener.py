from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from StellariaPact.cogs.Voting.listeners.DiscussionMessageListener import (
    DiscussionMessageListener,
)


@pytest.mark.asyncio
async def test_created_then_deleted_message_returns_activity_to_original_count() -> None:
    """验证禁言消息先新增后删除会向服务层提交相反的计数变化。"""
    # 构造目标论坛内的一条有效用户消息。
    thread = MagicMock(spec=discord.Thread)
    thread.id = 400
    thread.parent_id = 200
    message = MagicMock(spec=discord.Message)
    message.content = "这是有效发言"
    message.author = MagicMock(id=500, bot=False)
    message.channel = thread

    # 使用同一个业务逻辑接收创建和删除事件。
    bot = MagicMock()
    bot.config = {"channels": {"discussion": 200}}
    voting_cog = MagicMock()
    voting_cog.logic.handle_message_creation = AsyncMock()
    voting_cog.logic.handle_message_deletion = AsyncMock(return_value=None)
    listener = DiscussionMessageListener(bot, voting_cog)

    # 模拟禁言监听器删除消息后 Discord 产生的缓存内删除事件。
    with patch(
        "StellariaPact.cogs.Voting.listeners.DiscussionMessageListener.discord.Thread",
        type(thread),
    ):
        await listener.on_message(message)
        await listener.on_message_delete(message)

    created_qo = voting_cog.logic.handle_message_creation.await_args.args[0]
    deleted_qo = voting_cog.logic.handle_message_deletion.await_args.args[0]
    assert (created_qo.user_id, created_qo.thread_id, created_qo.change) == (500, 400, 1)
    assert (deleted_qo.user_id, deleted_qo.thread_id, deleted_qo.change) == (500, 400, -1)
