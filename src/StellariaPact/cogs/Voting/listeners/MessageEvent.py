"""定义跨 Bot 消息事件的数据契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

ID_FIELDS = ("message_id", "guild_id", "forum_id", "thread_id", "user_id")
EXPECTED_FIELDS = {"schema_version", "event_type", *ID_FIELDS}
MessageEventType = Literal["message_created", "message_deleted"]


@dataclass(frozen=True)
class MessageEvent:
    """保存经过校验的跨 Bot 消息事件。"""

    event_type: MessageEventType
    message_id: int
    guild_id: int
    forum_id: int
    thread_id: int
    user_id: int

    @classmethod
    def from_payload(cls, payload: object) -> MessageEvent:
        """从 HTTP JSON 请求体解析消息事件。"""
        # 请求体必须严格匹配当前版本的数据契约。
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        if set(payload) != EXPECTED_FIELDS:
            raise ValueError("request body has missing or unknown fields")

        # 协议版本必须使用整数类型，避免浮点数或布尔值混入。
        if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
            raise ValueError("unsupported schema_version")

        # 仅接受资格计数需要的创建和删除事件。
        raw_event_type = payload["event_type"]
        if raw_event_type not in {"message_created", "message_deleted"}:
            raise ValueError("unsupported event_type")
        event_type = cast(MessageEventType, raw_event_type)

        # Discord Snowflake 必须以正整数十进制字符串传输。
        parsed_ids: dict[str, int] = {}
        for field in ID_FIELDS:
            value = payload[field]
            if not isinstance(value, str) or not value.isdigit() or int(value) <= 0:
                raise ValueError(f"{field} must be a positive decimal string")
            parsed_ids[field] = int(value)

        # 将解析后的 ID 构造成不可变事件对象。
        return cls(event_type=event_type, **parsed_ids)  # type: ignore[arg-type]
