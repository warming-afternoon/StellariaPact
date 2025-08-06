from StellariaPact.share.BaseDto import BaseDto


class SubsequentObjectionDto(BaseDto):
    """
    封装当一个“后续异议”被创建时，生成管理员审核UI所需的数据。
    """

    objection_id: int
    objector_id: int
    objection_reason: str
    proposal_id: int
    proposal_title: str
    proposal_thread_id: int
