from enum import IntEnum


class VoteSessionType(IntEnum):
    PROPOSAL_FINAL = 0  # 正式投票
    OBJECTION_SUPPORT = 1  # 异议产生票收集
    OBJECTION_FINAL = 2  # 异议正式投票
    INTAKE_SUPPORT = 3  # 议案准入支持票收集
