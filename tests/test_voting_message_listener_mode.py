from types import SimpleNamespace
from unittest.mock import MagicMock

from StellariaPact.cogs.Voting import create_message_listener
from StellariaPact.cogs.Voting.listeners.DiscussionMessageListener import (
    DiscussionMessageListener,
)
from StellariaPact.cogs.Voting.listeners.MessageEventApiCog import MessageEventApiCog
from StellariaPact.share.RemoteMessageEventsConfig import RemoteMessageEventsConfig


def make_bot(remote_enabled: bool) -> MagicMock:
    """构造带指定消息来源模式的测试 Bot。"""
    # API 参数在本测试中不绑定端口，只用于构造监听器。
    bot = MagicMock()
    bot.remote_message_events = RemoteMessageEventsConfig(
        enabled=remote_enabled,
        bind_host="127.0.0.1",
        bind_port=8765,
        token="shared-secret" if remote_enabled else "",
    )
    bot.config = {"guild_id": 100, "channels": {"discussion": 200}}
    return bot


def test_local_mode_creates_only_discussion_listener() -> None:
    """验证本地模式只创建 Discord 资格消息监听器。"""
    # 使用本地模式配置选择监听器。
    listener = create_message_listener(make_bot(False), SimpleNamespace())  # type: ignore[arg-type]

    assert isinstance(listener, DiscussionMessageListener)
    assert not isinstance(listener, MessageEventApiCog)


def test_remote_mode_creates_only_message_event_api() -> None:
    """验证远端模式只创建 HTTP 消息事件接收端。"""
    # 使用远端模式配置选择监听器。
    listener = create_message_listener(make_bot(True), SimpleNamespace())  # type: ignore[arg-type]

    assert isinstance(listener, MessageEventApiCog)
    assert not isinstance(listener, DiscussionMessageListener)
