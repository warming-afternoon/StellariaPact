from dataclasses import dataclass


@dataclass(frozen=True)
class AbandonProposalQo:
    """
    用于废弃提案的查询对象。
    """

    thread_id: int
    reason: str
