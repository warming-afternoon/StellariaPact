from unittest.mock import patch

import pytest

from StellariaPact.share.RemoteMessageEventsConfig import RemoteMessageEventsConfig


def test_remote_message_events_default_to_local_mode() -> None:
    """验证未配置开关时默认使用本地消息监听模式。"""
    # 清理全部远端变量以模拟测试服务器的最小配置。
    with patch.dict(
        "os.environ",
        {
            "STELLARIA_EVENT_API_BIND_HOST": "",
            "STELLARIA_EVENT_API_PORT": "invalid",
            "STELLARIA_EVENT_API_TOKEN": "",
        },
        clear=False,
    ):
        with patch.dict(
            "os.environ",
            {},
            clear=False,
        ):
            # 显式删除开关以验证代码中的默认值。
            import os

            os.environ.pop("STELLARIA_REMOTE_MESSAGE_EVENTS_ENABLED", None)
            config = RemoteMessageEventsConfig.from_env()

    assert config.enabled is False
    assert config.create_discord_intents().message_content is True


def test_remote_mode_requires_complete_api_configuration() -> None:
    """验证远端模式缺少必要参数时直接拒绝启动配置。"""
    # 同时提供多个错误以验证启动日志可以一次指出全部问题。
    with patch.dict(
        "os.environ",
        {
            "STELLARIA_REMOTE_MESSAGE_EVENTS_ENABLED": "true",
            "STELLARIA_EVENT_API_BIND_HOST": "",
            "STELLARIA_EVENT_API_PORT": "70000",
            "STELLARIA_EVENT_API_TOKEN": "",
        },
        clear=False,
    ):
        with pytest.raises(ValueError) as error:
            RemoteMessageEventsConfig.from_env()

    message = str(error.value)
    assert "STELLARIA_EVENT_API_BIND_HOST" in message
    assert "STELLARIA_EVENT_API_PORT" in message
    assert "STELLARIA_EVENT_API_TOKEN" in message


def test_remote_mode_accepts_valid_api_configuration() -> None:
    """验证远端模式完整配置能够生成接收端配置对象。"""
    # 使用生产模式所需的全部环境变量。
    with patch.dict(
        "os.environ",
        {
            "STELLARIA_REMOTE_MESSAGE_EVENTS_ENABLED": "true",
            "STELLARIA_EVENT_API_BIND_HOST": "0.0.0.0",
            "STELLARIA_EVENT_API_PORT": "8765",
            "STELLARIA_EVENT_API_TOKEN": "shared-secret",
        },
        clear=False,
    ):
        config = RemoteMessageEventsConfig.from_env()

    assert config == RemoteMessageEventsConfig(
        enabled=True,
        bind_host="0.0.0.0",
        bind_port=8765,
        token="shared-secret",
    )
    assert config.create_discord_intents().message_content is False
