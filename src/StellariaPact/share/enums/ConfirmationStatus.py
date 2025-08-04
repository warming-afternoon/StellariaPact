from enum import IntEnum


class ConfirmationStatus(IntEnum):
    """确认会话状态"""

    PENDING = 0  # 待处理
    COMPLETED = 1  # 已完成
    CANCELED = 2  # 已取消