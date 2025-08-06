from ....share.BaseDto import BaseDto
from ....share.enums.ObjectionStatus import ObjectionStatus


class ObjectionDto(BaseDto):
    """
    异议的数据传输对象
    """

    id: int
    proposalId: int
    objectorId: int
    reason: str
    status: ObjectionStatus
    requiredVotes: int
    objectionThreadId: int | None
