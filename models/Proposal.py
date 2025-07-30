from datetime import datetime
from typing import List, TYPE_CHECKING
from sqlmodel import Field, text, Relationship
from models.BaseModel import BaseModel

if TYPE_CHECKING:
    from .Objection import Objection

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

    # --- 关系定义 ---
    objections: List["Objection"] = Relationship(back_populates="proposal")