from datetime import datetime, timezone

from sqlalchemy import Index
from sqlmodel import Field, text

from StellariaPact.models.BaseModel import BaseModel
from StellariaPact.share.database_types import UTCDateTime


class PunishmentRecord(BaseModel, table=True):
    """用户在帖子内受到处罚时的历史快照。"""

    __tablename__ = "punishment_record"  # type: ignore
    __table_args__ = (
        Index(
            "ix_punishment_record_thread_user_created",
            "thread_id",
            "target_user_id",
            "created_at",
        ),
    )

    guild_id: int = Field(index=True, description="服务器 Discord ID")
    """服务器 Discord ID。"""

    thread_id: int = Field(description="处罚发生的帖子 ID")
    """处罚发生的帖子 ID。"""

    target_user_id: int = Field(description="被处罚用户 Discord ID")
    """被处罚用户 Discord ID。"""

    moderator_id: int = Field(index=True, description="执行处罚的管理员 Discord ID")
    """执行处罚的管理员 Discord ID。"""

    reason: str = Field(description="处罚原因")
    """处罚原因。"""

    source_message_url: str | None = Field(default=None, description="违规触发消息链接")
    """违规触发消息链接。"""

    source_publicity_message_id: int | None = Field(
        default=None, description="原帖处罚公示消息 ID"
    )
    """原帖处罚公示消息 ID，与帖子 ID 共同定位消息。"""

    counts_toward_cumulative: bool = Field(default=False, description="是否计入累计处罚")
    """该记录是否参与累计处罚档位计算。"""

    lifted_at: datetime | None = Field(default=None, sa_type=UTCDateTime, description="解除时间")
    """解除登记时间，为空表示没有登记过解除。"""

    lifted_by_id: int | None = Field(default=None, description="解除操作人 ID")
    """执行解除操作的管理员 ID。"""

    lift_reason: str | None = Field(default=None, description="解除理由")
    """管理员填写的解除理由。"""

    publicity_guild_id: int | None = Field(default=None, description="正式处罚公示服务器 ID")
    """正式处罚公示服务器 ID。"""

    publicity_channel_id: int | None = Field(default=None, description="正式处罚公示频道 ID")
    """正式处罚公示频道 ID。"""

    publicity_message_id: int | None = Field(default=None, description="正式处罚公示消息 ID")
    """正式处罚公示消息 ID。"""

    voting_allowed: bool = Field(description="处罚后是否保留本帖投票权")
    """处罚后是否保留本帖投票权。"""

    mute_end_time: datetime | None = Field(
        default=None,
        sa_type=UTCDateTime,
        description="处罚时设置的禁言截止时间",
    )
    """处罚时设置的禁言截止时间。"""

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="处罚时间",
    )
    """处罚时间。"""
