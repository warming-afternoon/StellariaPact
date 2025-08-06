from ....share.BaseDto import BaseDto


class AbandonProposalQo(BaseDto):
    """
    用于废弃提案的查询对象。
    """

    thread_id: int
    reason: str
