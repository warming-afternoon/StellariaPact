from enum import IntEnum


class VoteSessionType(IntEnum):
    """投票会话类型枚举"""

    PROPOSAL_FINAL = 0
    """正式投票"""

    OBJECTION_SUPPORT = 1
    """异议产生票收集"""

    OBJECTION_FINAL = 2
    """异议正式投票"""

    INTAKE_SUPPORT = 3
    """议案准入支持票收集"""
