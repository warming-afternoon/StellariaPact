from ....share.BaseDto import BaseDto


class RaiseObjectionResultDto(BaseDto):
    """
    封装发起异议操作的结果。
    在两阶段提交流程中，此DTO负责从Logic层向Cog层传递所有必要信息。
    """

    is_first_objection: bool
    objection_id: int
    vote_session_id: int
    objector_id: int
    objection_reason: str
    required_votes: int
    proposal_id: int
    proposal_title: str
    proposal_thread_id: int
