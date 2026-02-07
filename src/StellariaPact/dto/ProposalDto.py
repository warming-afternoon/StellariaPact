from StellariaPact.share.BaseDto import BaseDto

from ..share.enums.ProposalStatus import ProposalStatus


class ProposalDto(BaseDto):
    """
    提案的数据传输对象
    """

    id: int
    """主键ID"""

    proposer_id: int
    """提案发起人的Discord ID"""

    title: str
    """提案标题"""

    content: str
    """提案内容"""

    status: ProposalStatus
    """提案当前状态: 0-讨论中, 1-执行中, 2-冻结中, 3-已废弃, 4-已否决, 5-已结束"""

    discussion_thread_id: int | None
    """Discord讨论帖的ID"""
