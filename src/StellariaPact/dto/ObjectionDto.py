from ..share.BaseDto import BaseDto
from ..share.enums.ObjectionStatus import ObjectionStatus


class ObjectionDto(BaseDto):
    """
    异议的数据传输对象
    """

    id: int
    proposal_id: int
    objector_id: int
    reason: str
    status: ObjectionStatus
    required_votes: int
    objection_thread_id: int | None
