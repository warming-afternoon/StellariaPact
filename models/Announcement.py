from datetime import datetime
from sqlmodel import Field, text
from models.BaseModel import BaseModel

class Announcement(BaseModel, table=True):
    """
    公示表模型
    """
    discussionThreadId: int = Field(unique=True, description="关联的Discord讨论帖ID")
    announcerId: int = Field(description="公示发起人的Discord ID")
    title: str = Field(description="公示标题")
    content: str = Field(description="公示内容")
    status: int = Field(default=0, index=True, description="公示状态: 0-进行中, 1-已结束")
    endTime: datetime = Field(description="公示截止时间")
    createdAt: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="创建时间"
    )