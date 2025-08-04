from StellariaPact.share.BaseDto import BaseDto


class CreateObjectionQo(BaseDto):
    """
    用于创建新异议的查询对象。
    """

    proposal_id: int
    objector_id: int
    reason: str
    required_votes: int
    status: int = 0
