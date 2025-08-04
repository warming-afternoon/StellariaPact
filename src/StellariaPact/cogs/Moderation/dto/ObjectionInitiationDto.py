from ....share.BaseDto import BaseDto


class ObjectionInitiationDto(BaseDto):
    """
    用于在发起异议的相关事件中传递数据
    """

    objection_id: int
    objector_id: int
    objection_reason: str
    required_votes: int
    proposal_id: int
    proposal_title: str
    proposal_thread_id: int
