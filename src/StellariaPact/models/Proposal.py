from datetime import datetime, timezone
from typing import TYPE_CHECKING, List

from sqlmodel import Field, Relationship, text

from StellariaPact.models.BaseModel import BaseModel
from StellariaPact.share.database_types import UTCDateTime
from StellariaPact.share.enums.ProposalStatus import ProposalStatus

if TYPE_CHECKING:
    from StellariaPact.models.Objection import Objection


class Proposal(BaseModel, table=True):
    """
    提案表模型
    """

    __tablename__ = "proposal"  # type: ignore

    discussion_thread_id: int = Field(unique=True, description="Discord讨论帖的ID")
    """Discord讨论帖的ID"""

    title: str = Field(description="提案标题")
    """提案标题"""

    content: str = Field(default="", description="提案内容")
    """提案内容"""

    proposer_id: int = Field(index=True, description="提案发起人的Discord ID")
    """提案发起人的Discord ID"""

    status: int = Field(
        default=ProposalStatus.DISCUSSION,
        index=True,
        description=(
            "提案当前状态: 0-讨论中, 1-执行中, 2-冻结中, "
            "3-已废弃, 4-已否决, 5-已结束, 6-异议中"
        ),
    )
    """提案当前状态: 0-讨论中, 1-执行中, 2-冻结中, 3-已废弃, 4-已否决, 5-已结束, 6-异议中"""

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=UTCDateTime,
        sa_column_kwargs={"server_default": text("CURRENT_TIMESTAMP")},
        description="创建时间",
    )
    """创建时间"""

    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_type=UTCDateTime,
        sa_column_kwargs={
            "server_default": text("CURRENT_TIMESTAMP"),
            "onupdate": text("CURRENT_TIMESTAMP"),
        },
        description="最后更新时间",
    )
    """最后更新时间"""

    # --- 关系定义 ---
    objections: List["Objection"] = Relationship(back_populates="proposal")
