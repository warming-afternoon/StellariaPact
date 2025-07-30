from datetime import datetime
from sqlmodel import Field, text
from models.BaseModel import BaseModel

class Proposal(BaseModel, table=True):
    """
    提案表模型
    """
    discussionThreadId: int = Field(unique=True, description="Discord讨论帖的ID")
    proposerId: int = Field(index=True, description="提案发起人的Discord ID")
    status: int = Field(default=0, index=True, description="提案当前状态: 0-讨论中, 1-执行中, 2-冻结中, 3-已废弃, 4-已否决, 5-已结束")
    createdAt: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="创建时间"
    )
    updatedAt: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={
            "server_default": text("CURRENT_TIMESTAMP"),
            "onupdate": text("CURRENT_TIMESTAMP")
        },
        description="最后更新时间"
    )