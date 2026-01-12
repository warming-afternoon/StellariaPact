from StellariaPact.share.BaseDto import BaseDto

from ..share.enums.ObjectionStatus import ObjectionStatus


class ObjectionDto(BaseDto):
    """
    异议的数据传输对象
    """

    id: int
    """主键ID"""

    proposal_id: int
    """关联的提案ID"""

    objector_id: int
    """异议发起人的Discord ID"""

    reason: str
    """反对理由"""

    status: ObjectionStatus
    """异议当前状态: 0-待审核, 1-异议贴产生票收集中, 2-异议投票中, 3-已通过, 4-已否决"""

    required_votes: int
    """触发投票所需的反对票数"""

    objection_thread_id: int | None
    """异议讨论帖的ID"""
