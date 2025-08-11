from StellariaPact.share.BaseDto import BaseDto
from StellariaPact.share.enums.ObjectionStatus import ObjectionStatus


class CreateObjectionQo(BaseDto):
    """
    创建异议的查询对象
    """

    proposal_id: int
    objector_id: int
    reason: str
    required_votes: int
    status: ObjectionStatus