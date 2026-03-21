from datetime import datetime, timezone

from sqlmodel import Field, text

from StellariaPact.models.BaseModel import BaseModel
from StellariaPact.share.database_types import UTCDateTime


class VoteMessageMirror(BaseModel, table=True):
    """
    存储额外复制的投票镜像消息关联
    """

    __tablename__ = "vote_message_mirror"  # type: ignore

    session_id: int = Field(index=True, description="关联的投票会话ID")
    """关联的投票会话ID"""

    guild_id: int = Field(index=True, description="服务器ID")
    """服务器ID"""

    channel_id: int = Field(index=True, description="镜像所在的频道或帖子ID")
    """镜像所在的频道或帖子ID"""

    message_id: int = Field(index=True, description="镜像消息的ID")
    """镜像消息的ID"""

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="创建时间",
    )
    """创建时间"""
