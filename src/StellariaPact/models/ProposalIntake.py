from datetime import datetime
from typing import Optional

from sqlmodel import Field

from StellariaPact.models.BaseModel import BaseModel
from StellariaPact.share.enums import IntakeStatus


class ProposalIntake(BaseModel, table=True):
    """
    提案预审核模型
    """

    __tablename__ = "proposal_intake"  # type: ignore

    guild_id: int = Field(index=True, description="服务器ID")
    """服务器ID"""
    author_id: int = Field(index=True, description="提案提出者的用户ID")
    """提案提出者的用户ID"""

    # 提案核心字段
    title: str = Field(description="标题")
    """标题"""
    reason: str = Field(description="提案原因")
    """提案原因"""
    motion: str = Field(description="议案动议")
    """议案动议"""
    implementation: str = Field(description="执行方案")
    """执行方案"""
    executor: str = Field(description="执行人")
    """执行人"""

    status: int = Field(default=IntakeStatus.PENDING_REVIEW, index=True)
    """审核状态，0=待审核，1=批准，2=拒绝，3=需要修改"""
    review_thread_id: Optional[int] = Field(default=None, description="审核贴ID")
    """审核贴ID"""
    discussion_thread_id: Optional[int] = Field(default=None, description="讨论帖ID")
    """讨论帖ID"""
    voting_message_id: Optional[int] = Field(default=None, description="投票频道消息ID")
    """投票频道消息ID"""
    required_votes: int = Field(default=20, description="需多少票才能正式发布")
    """需多少票才能正式发布"""

    # 审核相关字段
    reviewer_id: Optional[int] = Field(default=None, description="审核人用户ID")
    """审核人用户ID"""
    reviewed_at: Optional[datetime] = Field(default=None, description="审核时间")
    """审核时间"""
    review_comment: Optional[str] = Field(default=None, description="审核意见")
    """审核意见"""
