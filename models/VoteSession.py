from typing import Optional, List, TYPE_CHECKING
from datetime import datetime
from sqlmodel import Field, Relationship, text
from models.BaseModel import BaseModel
from models.Objection import Objection

if TYPE_CHECKING:
    from models.UserVote import UserVote

class VoteSession(BaseModel, table=True):
    """
    投票会话表
    """

    contextThreadId: int = Field(index=True, description="投票发生的上下文帖子ID")
    objectionId: Optional[int] = Field(default=None, foreign_key="objection.id", description="关联的异议ID")
    anonymousFlag: bool = Field(default=True, description="是否为匿名投票")
    status: int = Field(default=1, index=True, description="投票状态: 0-已结束, 1-进行中")
    endTime: Optional[datetime] = Field(default=None, description="投票截止时间")
    createdAt: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="创建时间"
    )

    # --- 关系定义 ---
    objection: Optional[Objection] = Relationship(back_populates="vote_session")
    userVotes: List["UserVote"] = Relationship(back_populates="session")