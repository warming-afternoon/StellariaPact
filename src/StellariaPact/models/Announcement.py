from datetime import datetime
from typing import TYPE_CHECKING, List

from sqlmodel import Field, Relationship, text

from StellariaPact.models.BaseModel import BaseModel

if TYPE_CHECKING:
    from StellariaPact.models.AnnouncementChannelMonitor import AnnouncementChannelMonitor


class Announcement(BaseModel, table=True):
    """
    公示表模型
    """

    discussionThreadId: int = Field(unique=True, description="关联的Discord讨论帖ID")
    announcerId: int = Field(description="公示发起人的Discord ID")
    title: str = Field(description="公示标题")
    content: str = Field(description="公示内容")
    status: int = Field(default=1, index=True, description="公示状态: 0-已结束, 1-进行中")
    endTime: datetime = Field(description="公示截止时间")
    createdAt: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="创建时间",
    )

    # --- 关系定义 ---
    channelMonitors: List["AnnouncementChannelMonitor"] = Relationship(
        back_populates="announcement"
    )
