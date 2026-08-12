"""定义远端消息事件模式的环境配置。"""

from __future__ import annotations

import os
from dataclasses import dataclass

import discord


@dataclass(frozen=True)
class RemoteMessageEventsConfig:
    """保存提案 Bot 的消息事件来源和 HTTP 接收端配置。"""

    enabled: bool
    bind_host: str
    bind_port: int
    token: str

    def create_discord_intents(self) -> discord.Intents:
        """根据消息事件来源创建提案 Bot 使用的 Discord Intents。"""
        # 两种模式都使用默认非特权事件集合。
        intents = discord.Intents.default()

        # 本地模式读取正文，远端模式只接收禁言删除所需的消息元数据。
        intents.message_content = not self.enabled
        intents.members = False
        return intents

    @classmethod
    def from_env(cls) -> RemoteMessageEventsConfig:
        """读取环境变量并在远端模式下严格校验配置。"""
        # 远端模式默认关闭，测试 Bot 可直接使用本地消息监听。
        enabled = cls._parse_enabled(os.getenv("STELLARIA_REMOTE_MESSAGE_EVENTS_ENABLED", "false"))
        bind_host = os.getenv("STELLARIA_EVENT_API_BIND_HOST", "0.0.0.0").strip()
        bind_port = cls._parse_port(os.getenv("STELLARIA_EVENT_API_PORT", "8765"))
        token = os.getenv("STELLARIA_EVENT_API_TOKEN", "").strip()

        # 本地模式不会启动 HTTP 服务，因此不要求配置共享令牌。
        if enabled:
            errors: list[str] = []
            if not bind_host:
                errors.append("STELLARIA_EVENT_API_BIND_HOST is required")
            if bind_port is None:
                errors.append("STELLARIA_EVENT_API_PORT must be between 1 and 65535")
            if not token:
                errors.append("STELLARIA_EVENT_API_TOKEN is required")
            if errors:
                message = "Invalid remote message event configuration: " + "; ".join(errors)
                raise ValueError(message)

        # 本地模式下无效端口不会被使用，以默认端口保持配置对象类型稳定。
        return cls(
            enabled=enabled,
            bind_host=bind_host or "0.0.0.0",
            bind_port=bind_port or 8765,
            token=token,
        )

    @staticmethod
    def _parse_enabled(value: str) -> bool:
        """解析远端消息事件布尔开关。"""
        # 只接受明确布尔值，避免拼写错误悄悄切换监听模式。
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError("STELLARIA_REMOTE_MESSAGE_EVENTS_ENABLED must be a boolean value")

    @staticmethod
    def _parse_port(value: str) -> int | None:
        """解析 HTTP 接收端口并限制在合法 TCP 范围内。"""
        # 非整数值直接视为无效配置。
        try:
            port = int(value)
        except ValueError:
            return None

        # 仅允许可绑定的标准 TCP 端口范围。
        return port if 1 <= port <= 65535 else None
