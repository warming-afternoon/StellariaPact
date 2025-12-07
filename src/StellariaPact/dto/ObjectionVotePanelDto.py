from StellariaPact.share.BaseDto import BaseDto


class ObjectionVotePanelDto(BaseDto):
    """
    封装创建“异议投票收集面板”所需的所有信息。
    当一个异议（无论是首次还是后续批准）需要开始收集支持票时，
    由Logic层构建并传递给Cog层。
    """

    objection_id: int
    vote_session_id: int
    objector_id: int
    objection_reason: str
    required_votes: int
    proposal_id: int
    proposal_title: str
    proposal_thread_id: int
