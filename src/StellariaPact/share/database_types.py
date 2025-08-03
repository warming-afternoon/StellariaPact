import json
from typing import Any

from sqlalchemy import TEXT, TypeDecorator
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


# 优先使用 PostgreSQL 的 JSONB 类型，如果不是 PG，则回退到自定义的 JsonEncoded 类型
JSON_TYPE = JSONB().with_variant(JsonEncoded, "sqlite", "mysql")
