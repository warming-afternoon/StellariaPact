from datetime import datetime
from typing import Dict, List

from sqlalchemy import Column, Index, text
from sqlmodel import Field

from StellariaPact.models.BaseModel import BaseModel
from StellariaPact.share.database_types import JSON_TYPE
from StellariaPact.share.enums.ConfirmationStatus import ConfirmationStatus


class ConfirmationSession(BaseModel, table=True):
    """
    通用确认会话模型，用于处理需要多方确认的流程。
    """

    context: str = Field(index=True, description="确认会话的上下文，如 'proposal_execution'")
    targetId: int = Field(index=True, description="关联的业务对象ID，如 Proposal.id")
    messageId: int | None = Field(default=None, unique=True, description="机器人发送的确认消息ID")
    status: int = Field(
        default=ConfirmationStatus.PENDING,
        index=True,
        description="会话状态: 0-待处理, 1-已完成, 2-已取消",
    )
    requiredRoles: List[str] = Field(
        default=[], sa_column=Column(JSON_TYPE), description="需要进行确认的角色列表"
    )
    confirmedParties: Dict[str, int] = Field(
        default={}, sa_column=Column(JSON_TYPE), description="已确认的角色及用户ID"
    )
    cancelerId: int | None = Field(default=None, description="取消该会话的用户ID")
    createdAt: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="创建时间",
    )
    updatedAt: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={
            "server_default": text("CURRENT_TIMESTAMP"),
            "onupdate": text("CURRENT_TIMESTAMP"),
        },
        description="最后更新时间",
    )
    __table_args__ = (
        Index(
            "idx_active_confirmation_session",
            "context",
            "targetId",
            unique=True,
            sqlite_where=text(f"status = {ConfirmationStatus.PENDING}"),
        ),
    )
