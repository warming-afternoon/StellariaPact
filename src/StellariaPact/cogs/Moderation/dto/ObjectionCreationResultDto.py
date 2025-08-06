from dataclasses import dataclass


@dataclass
class ObjectionCreationResultDto:
    """
    封装创建异议及其关联投票会话“空壳”后的结果。
    """

    objection_id: int
    vote_session_id: int
