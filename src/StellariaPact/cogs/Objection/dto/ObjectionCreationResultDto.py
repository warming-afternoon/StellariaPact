from StellariaPact.share.BaseDto import BaseDto


class ObjectionCreationResultDto(BaseDto):
    """
    封装创建异议及其关联投票会话“空壳”后的结果。
    """

    objection_id: int
    vote_session_id: int
