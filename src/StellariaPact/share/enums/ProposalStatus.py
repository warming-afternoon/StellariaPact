from enum import IntEnum


class ProposalStatus(IntEnum):
    """提案当前状态"""

    DISCUSSION = 0  # 讨论中
    EXECUTING = 1  # 执行中
    FROZEN = 2  # 冻结中
    ABANDONED = 3  # 已废弃
    REJECTED = 4  # 已否决
    FINISHED = 5  # 已结束