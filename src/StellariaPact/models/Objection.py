from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, text

from StellariaPact.models.BaseModel import BaseModel
from StellariaPact.models.Proposal import Proposal
from StellariaPact.share.enums.ObjectionStatus import ObjectionStatus

if TYPE_CHECKING:
    from StellariaPact.models.VoteSession import VoteSession


class Objection(BaseModel, table=True):
    """
    异议表模型
    """

    proposalId: int = Field(foreign_key="proposal.id", index=True, description="关联的提案ID")
    objectorId: int = Field(index=True, description="异议发起人的Discord ID")
    reason: str = Field(description="反对理由")
    objectionThreadId: Optional[int] = Field(
        index=True, default=None, description="异议讨论帖的ID"
    )
    reviewThreadId: Optional[int] = Field(index=True, default=None, description="管理员审核帖的ID")
    status: int = Field(
        default=ObjectionStatus.PENDING_REVIEW,
        description=(
            "异议当前状态: 0-待审核, 1-异议贴产生票收集中, 2-异议投票中, 3-已通过, 4-已否决"
        ),
    )
    requiredVotes: int = Field(description="触发投票所需的反对票数")
    createdAt: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="创建时间",
    )

    # --- 关系定义 ---
    proposal: Optional[Proposal] = Relationship(back_populates="objections")
    vote_session: Optional["VoteSession"] = Relationship(back_populates="objection")
