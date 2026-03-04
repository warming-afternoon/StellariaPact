import json
from datetime import timezone
from typing import Any

from sqlalchemy import TEXT, DateTime, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB


class JsonEncoded(TypeDecorator):
    """
    将 Python 对象序列化为 JSON 字符串存储在 TEXT 类型的列中。
    为不原生支持 JSON 的数据库（如 SQLite）提供兼容性。
    """

    impl = TEXT
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value)

    def process_result_value(self, value: str | None, dialect: Any) -> Any | None:
        if value is None:
            return None
        return json.loads(value)


class UTCDateTime(TypeDecorator):
    """
    用于 SQLite 的自定义时间类型。
    存入数据库前：确保是 UTC 时间，并剥离 tzinfo (因为 SQLite 不支持时区存储)。
    从数据库读取后：强制附加 timezone.utc 时区信息。
    """
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            # 如果传入的是 Naive 时间，隐式视为 UTC
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            else:
                # 如果传入了其他时区的时间，统一转换为 UTC
                value = value.astimezone(timezone.utc)
            # 剥离 tzinfo，返回 Naive UTC 时间给 SQLite 存储
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            # SQLite 取出的数据是 Naive 的，强制为其赋予 UTC 时区
            return value.replace(tzinfo=timezone.utc)
        return value


# 优先使用 PostgreSQL 的 JSONB 类型，如果不是 PG，则回退到自定义的 JsonEncoded 类型
JSON_TYPE = JSONB().with_variant(JsonEncoded, "sqlite", "mysql")
