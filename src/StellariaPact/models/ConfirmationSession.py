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

    __tablename__ = "confirmation_session"  # type: ignore

    context: str = Field(index=True, description="确认会话的上下文，如 'proposal_execution'")
    target_id: int = Field(index=True, description="关联的业务对象ID，如 Proposal.id")
    message_id: int | None = Field(default=None, unique=True, description="机器人发送的确认消息ID")
    status: int = Field(
        default=ConfirmationStatus.PENDING,
        index=True,
        description="会话状态: 0-待处理, 1-已完成, 2-已取消",
    )
    required_roles: List[str] = Field(
        default=[], sa_column=Column(JSON_TYPE), description="需要进行确认的角色列表"
    )
    confirmed_parties: Dict[str, int] = Field(
        default={}, sa_column=Column(JSON_TYPE), description="已确认的角色及用户ID"
    )
    canceler_id: int | None = Field(default=None, description="取消该会话的用户ID")
    reason: str | None = Field(default=None, description="执行此操作的原因")
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="创建时间",
    )
    updated_at: datetime = Field(
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
            "target_id",
            unique=True,
            sqlite_where=text(f"status = {ConfirmationStatus.PENDING}"),
        ),
    )
