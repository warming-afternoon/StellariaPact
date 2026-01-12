from datetime import datetime

from StellariaPact.share.BaseDto import BaseDto
from StellariaPact.share.enums.IntakeStatus import IntakeStatus


class ProposalIntakeDto(BaseDto):
    """
    提案草案的数据传输对象
    """

    id: int
    """主键ID"""

    guild_id: int
    """服务器ID"""

    author_id: int
    """提案提出者的用户ID"""

    title: str
    """标题"""

    reason: str
    """提案原因"""

    motion: str
    """议案动议"""

    implementation: str
    """执行方案"""

    executor: str
    """执行人"""

    status: IntakeStatus
    """审核状态，0=待审核，1=支持票收集中，2=已发布，3=已拒绝，4=需要修改"""

    review_thread_id: int | None
    """审核贴ID"""

    discussion_thread_id: int | None
    """讨论帖ID"""

    voting_message_id: int | None
    """投票频道消息ID"""

    required_votes: int
    """需多少票才能正式发布"""

    reviewer_id: int | None
    """审核人用户ID"""

    reviewed_at: datetime | None
    """审核时间"""

    review_comment: str | None
    """审核意见"""
