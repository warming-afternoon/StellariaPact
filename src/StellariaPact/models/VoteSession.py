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

    __tablename__ = "vote_session"  # type: ignore

    session_type: int = Field(
        default=0, index=True, description="投票类型, 0-提案, 1-异议支持, 2-异议, 3-草案"
    )
    """投票类型, 0-提案, 1-异议支持, 2-异议, 3-草案"""

    total_choices: int = Field(default=0, description="选项总数")
    """选项总数"""

    proposal_id: Optional[int] = Field(default=None, description="关联的提案ID")
    """关联的提案ID"""

    objection_id: Optional[int] = Field(default=None, description="关联的异议ID")
    """关联的异议ID"""

    intake_id: Optional[int] = Field(default=None, description="关联的草案ID")
    """关联的草案ID"""

    guild_id: int = Field(index=True, description="服务器ID")
    """服务器ID"""

    context_thread_id: int = Field(index=True, description="投票发生的频道ID")
    """投票发生的频道ID"""

    context_message_id: Optional[int] = Field(
        default=None, index=True, description="投票面板消息的ID"
    )
    """投票面板消息的ID"""

    voting_channel_message_id: Optional[int] = Field(
        default=None, index=True, description="投票频道中镜像投票消息的ID"
    )
    """投票频道中镜像投票消息的ID"""

    anonymous_flag: bool = Field(default=True, description="是否为匿名投票")
    """是否为匿名投票"""

    realtime_flag: bool = Field(default=True, description="是否实时展示投票进度")
    """是否实时展示投票进度"""

    notify_flag: bool = Field(default=True, description="投票结束时是否通知相关方")
    """投票结束时是否通知相关方"""

    status: int = Field(default=1, index=True, description="投票状态: 0-已结束, 1-进行中")
    """投票状态: 0-已结束, 1-进行中"""

    start_time: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="投票开始时间",
    )
    """投票开始时间"""

    end_time: Optional[datetime] = Field(default=None, description="投票截止时间")
    """投票截止时间"""

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="创建时间",
    )
    """创建时间"""

    # --- 关系定义 ---
    objection: Optional[Objection] = Relationship(back_populates="vote_session")
    userVotes: List["UserVote"] = Relationship(back_populates="session")
