from enum import StrEnum


class PunishmentType(StrEnum):
    """全局提案处罚类型。"""

    PERMANENT_VOTING = "permanent_voting"
    """永久剥夺全部提案类投票资格"""

    PROPOSAL_VIOLATION = "proposal_violation"
    """限时禁止参与提案投票、讨论、异议及提案创建"""
