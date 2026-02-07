from StellariaPact.share.BaseDto import BaseDto


class ObjectionVotePanelDto(BaseDto):
    """
    封装创建“异议投票收集面板”所需的所有信息。
    当一个异议（无论是首次还是后续批准）需要开始收集支持票时，
    由Logic层构建并传递给Cog层。
    """

    objection_id: int
    """异议ID"""

    vote_session_id: int
    """投票会话ID"""

    objector_id: int
    """异议发起人的Discord ID"""

    objection_reason: str
    """反对理由"""

    required_votes: int
    """触发投票所需的反对票数"""

    proposal_id: int
    """提案ID"""

    proposal_title: str
    """提案标题"""

    proposal_thread_id: int
    """提案讨论帖ID"""
