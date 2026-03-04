from datetime import datetime, timezone
from typing import TYPE_CHECKING, List

from sqlmodel import Field, Relationship, text

from StellariaPact.models.BaseModel import BaseModel
from StellariaPact.share.database_types import UTCDateTime

if TYPE_CHECKING:
    from StellariaPact.models.AnnouncementChannelMonitor import AnnouncementChannelMonitor


class Announcement(BaseModel, table=True):
    """
    公示表模型
    """

    __tablename__ = "announcement"  # type: ignore

    discussion_thread_id: int = Field(description="关联的Discord讨论帖ID")
    """关联的Discord讨论帖ID"""

    announcer_id: int = Field(description="公示发起人的Discord ID")
    """公示发起人的Discord ID"""

    title: str = Field(description="公示标题")
    """公示标题"""

    content: str = Field(description="公示内容")
    """公示内容"""

    status: int = Field(default=1, index=True, description="公示状态: 0-已结束, 1-进行中")
    """公示状态: 0-已结束, 1-进行中"""

    end_time: datetime = Field(sa_type=UTCDateTime, description="公示截止时间")
    """公示截止时间"""

    auto_execute: bool = Field(default=True, description="公示结束后是否自动进入执行阶段")
    """公示结束后是否自动进入执行阶段"""

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="创建时间",
    )
    """创建时间"""

    # --- 关系定义 ---
    channel_monitors: List["AnnouncementChannelMonitor"] = Relationship(
        back_populates="announcement"
    )
