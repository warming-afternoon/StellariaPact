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

    __tablename__ = "user_vote"  # type: ignore

    session_id: int = Field(
        foreign_key="vote_session.id", index=True, description="关联的投票会话ID"
    )
    user_id: int = Field(index=True, description="投票用户的Discord ID")
    choice: int = Field(description="用户的选项: 0-反对, 1-赞成")
    choice_index: int = Field(default=1, description="投票选项索引")
    voted_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="投票时间",
    )

    # --- 关系定义 ---
    session: Optional["VoteSession"] = Relationship(back_populates="userVotes")

    @declared_attr  # type: ignore
    def __table_args__(cls):
        return (
            UniqueConstraint(
                cls.session_id,  # type: ignore
                cls.user_id,  # type: ignore
                cls.choice_index,  # type: ignore
                name="uk_user_vote_option",
            ),
        )
