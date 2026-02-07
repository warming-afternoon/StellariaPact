from enum import IntEnum


class IntakeStatus(IntEnum):
    PENDING_REVIEW = 0  # 待审核
    SUPPORT_COLLECTING = 1  # 支持票收集中
    APPROVED = 2  # 已通过
    REJECTED = 3  # 已拒绝
    MODIFICATION_REQUIRED = 4  # 需修改
