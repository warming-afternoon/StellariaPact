from enum import IntEnum


class VoteDuration(IntEnum):
    """投票持续时间枚举（以小时为单位）"""

    PROPOSAL_DEFAULT = 72
    """提案默认投票持续时间（72小时）"""

    OBJECTION_DEFAULT = 72
    """异议默认投票持续时间（72小时）"""
