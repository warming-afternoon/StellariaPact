from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import UniqueConstraint
from sqlalchemy.ext.declarative import declared_attr
from sqlmodel import Field, Relationship, text

from StellariaPact.models.BaseModel import BaseModel

if TYPE_CHECKING:
    from StellariaPact.models.VoteSession import VoteSession


class UserVote(BaseModel, table=True):
    """
    用户投票记录表模型
    """

    sessionId: int = Field(
        foreign_key="votesession.id", index=True, description="关联的投票会话ID"
    )
    userId: int = Field(index=True, description="投票用户的Discord ID")
    choice: int = Field(description="用户的选项: 0-反对, 1-赞成")
    votedAt: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="投票时间",
    )

    # --- 关系定义 ---
    session: Optional["VoteSession"] = Relationship(back_populates="userVotes")

    @declared_attr
    def __table_args__(cls):
        return (UniqueConstraint(cls.sessionId, cls.userId, name="unique_user_vote_per_session"),)
