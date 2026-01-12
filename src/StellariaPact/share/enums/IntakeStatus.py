from enum import IntEnum


class IntakeStatus(IntEnum):
    """议案准入状态枚举"""

    PENDING_REVIEW = 0
    """待审核"""

    SUPPORT_COLLECTING = 1
    """支持票收集中(已通过)"""

    APPROVED = 2
    """已发布"""

    REJECTED = 3
    """已拒绝"""

    MODIFICATION_REQUIRED = 4
    """需修改"""
