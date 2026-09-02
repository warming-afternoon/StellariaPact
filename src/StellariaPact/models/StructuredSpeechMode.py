from datetime import datetime, timezone

from sqlalchemy import Index
from sqlmodel import Field, text

from StellariaPact.models.BaseModel import BaseModel
from StellariaPact.share.database_types import UTCDateTime


class StructuredSpeechMode(BaseModel, table=True):
    """保存单个讨论帖子的模板发言模式设置。"""

    __tablename__ = "structured_speech_mode"  # type: ignore
    __table_args__ = (
        Index("uq_structured_speech_mode_thread", "thread_id", unique=True),
        Index("ix_structured_speech_mode_status", "status"),
    )

    guild_id: int = Field(description="Discord 服务器 ID")
    """表示模式所属的 Discord 服务器 ID。"""

    forum_id: int = Field(description="父讨论论坛 ID")
    """表示讨论帖子所属的父论坛频道 ID。"""

    thread_id: int = Field(description="讨论帖子 ID")
    """表示启用模板发言模式的讨论帖子 ID。"""

    status: str = Field(default="inactive", max_length=16)
    """表示模式当前的持久化状态或切换过渡状态。"""

    interval_seconds: int = Field(default=120)
    """表示普通用户通过 Bot 发言的间隔秒数。"""

    proposer_cooldown_exempt: bool = Field(default=True)
    """表示提案主是否豁免通过 Bot 发言的时间间隔。"""

    previous_slowmode_delay: int = Field(default=0)
    """表示开启模式前保存的帖子慢速模式秒数。"""

    enabled_by_id: int = Field(description="最近一次操作人的 Discord ID")
    """表示最近一次切换或更新模式的操作人 Discord ID。"""

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
    )
    """表示模式记录的创建时间。"""

    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=UTCDateTime,
        sa_column_kwargs={
            "server_default": text("CURRENT_TIMESTAMP"),
            "onupdate": text("CURRENT_TIMESTAMP"),
        },
    )
    """表示模式记录最近一次更新的时间。"""
