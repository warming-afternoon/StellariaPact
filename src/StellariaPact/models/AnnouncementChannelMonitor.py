from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import UniqueConstraint
from sqlalchemy.ext.declarative import declared_attr
from sqlmodel import Field, Relationship, text

from StellariaPact.models.BaseModel import BaseModel

if TYPE_CHECKING:
    from StellariaPact.models.Announcement import Announcement


class AnnouncementChannelMonitor(BaseModel, table=True):
    """
    公示在特定频道中的周期性重复发布监控表
    """

    announcementId: int = Field(
        foreign_key="announcement.id", index=True, description="关联的公示ID"
    )
    channelId: int = Field(index=True, description="被监控的Discord频道ID")
    messageThreshold: int = Field(description="触发重复公示所需的消息数量阈值")
    timeIntervalMinutes: int = Field(description="触发重复公示所需的时间间隔（分钟）")
    messageCountSinceLast: int = Field(default=0, description="自上次公示以来的消息计数")
    lastRepostAt: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="上次执行重复公示的时间",
    )

    # --- 关系定义 ---
    announcement: Optional["Announcement"] = Relationship(back_populates="channelMonitors")

    @declared_attr
    def __table_args__(cls):
        # 复合唯一约束
        return (
            UniqueConstraint(
                cls.announcementId,
                cls.channelId,
                name="uq_announcement_channel",
            ),
        )
