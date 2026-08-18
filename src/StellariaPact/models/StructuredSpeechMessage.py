from datetime import datetime, timezone

from sqlalchemy import Index
from sqlmodel import Field, text

from StellariaPact.models.BaseModel import BaseModel
from StellariaPact.share.database_types import UTCDateTime


class StructuredSpeechMessage(BaseModel, table=True):
    """保存结构化 Webhook 消息元数据，但不保存消息内容。"""

    __tablename__ = "structured_speech_message"  # type: ignore
    __table_args__ = (
        Index("uq_structured_speech_message_discord", "message_id", unique=True),
        Index("ix_structured_speech_message_webhook", "webhook_id"),
        Index(
            "ix_structured_speech_message_thread_user_created",
            "thread_id",
            "user_id",
            "created_at",
        ),
    )

    message_id: int = Field(description="Discord 消息 ID")
    """表示结构化 Webhook 消息的 Discord 消息 ID。"""

    webhook_id: int = Field(description="发送消息的 Discord Webhook ID")
    """表示发送结构化消息的 Discord Webhook ID。"""

    guild_id: int = Field(description="Discord 服务器 ID")
    """表示消息所属的 Discord 服务器 ID。"""

    thread_id: int = Field(description="讨论帖子 ID")
    """表示消息所在的讨论帖子 ID。"""

    user_id: int = Field(description="原发言用户 Discord ID")
    """表示通过 Bot 提交发言的原用户 Discord ID。"""

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
    )
    """表示结构化消息成功创建的时间。"""

    deleted_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    """表示消息删除回滚被首次认领的时间。"""
