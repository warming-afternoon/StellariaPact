from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlmodel import Field, Relationship, text

from StellariaPact.models.BaseModel import BaseModel
from StellariaPact.models.Objection import Objection

if TYPE_CHECKING:
    from StellariaPact.models.UserVote import UserVote


class VoteSession(BaseModel, table=True):
    """
    投票会话表
    """

    contextThreadId: int = Field(index=True, description="投票发生的频道ID")
    objectionId: Optional[int] = Field(
        default=None, foreign_key="objection.id", description="关联的异议ID"
    )
    contextMessageId: Optional[int] = Field(
        default=None, index=True, description="投票面板消息的ID"
    )
    votingChannelMessageId: Optional[int] = Field(
        default=None, index=True, description="投票频道中镜像投票消息的ID"
    )
    anonymousFlag: bool = Field(default=True, description="是否为匿名投票")
    realtimeFlag: bool = Field(default=True, description="是否实时展示投票进度")
    notifyFlag: bool = Field(default=True, description="投票结束时是否通知相关方")
    status: int = Field(default=1, index=True, description="投票状态: 0-已结束, 1-进行中")
    endTime: Optional[datetime] = Field(default=None, description="投票截止时间")
    createdAt: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="创建时间",
    )

    # --- 关系定义 ---
    objection: Optional[Objection] = Relationship(back_populates="vote_session")
    userVotes: List["UserVote"] = Relationship(back_populates="session")
