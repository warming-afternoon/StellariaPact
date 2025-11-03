from enum import IntEnum


class VoteDuration(IntEnum):
    """
    定义投票持续时间的标准值（以小时为单位）。
    """

    PROPOSAL_DEFAULT = 72
    OBJECTION_DEFAULT = 72
