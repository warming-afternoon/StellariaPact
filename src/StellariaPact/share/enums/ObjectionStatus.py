from enum import IntEnum


class ObjectionStatus(IntEnum):
    """异议当前状态"""

    PENDING_REVIEW = 0  # 待审核
    COLLECTING_VOTES = 1  # 异议贴产生票收集中
    VOTING = 2  # 异议投票中
    PASSED = 3  # 已通过
    REJECTED = 4  # 已否决
