from typing import Optional, TYPE_CHECKING
from datetime import datetime
from sqlmodel import Field, Relationship, SQLModel, text
from sqlalchemy import UniqueConstraint
from models.BaseModel import BaseModel

if TYPE_CHECKING:
    from models.VoteSession import VoteSession

class UserVote(BaseModel, table=True):
    """
    用户投票记录表模型
    """
    # 定义复合唯一约束，确保 (sessionId, userId) 的组合是唯一的
    __table_args__ = (
        UniqueConstraint("sessionId", "userId", name="unique_user_vote_per_session"),
    )

    sessionId: int = Field(foreign_key="votesession.id", description="关联的投票会话ID")
    userId: int = Field(index=True, description="投票用户的Discord ID")
    choice: int = Field(description="用户的选项: 0-反对, 1-赞成")
    votedAt: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="投票时间"
    )

    # --- 关系定义 ---
    session: Optional["VoteSession"] = Relationship(back_populates="userVotes")