from enum import IntEnum


class VoteOptionStatus(IntEnum):
    """投票选项的独立状态。"""

    CLOSED = 0
    """已结束，仅供历史查看。"""

    ACTIVE = 1
    """进行中，允许投票和撤票。"""
