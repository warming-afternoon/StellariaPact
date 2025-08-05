from dataclasses import dataclass


@dataclass
class ObjectionCreationResultDto:
    """
    封装创建异议及其关联投票会话“空壳”后的结果。
    只包含安全的、原始的数据类型。
    """

    objection_id: int
    vote_session_id: int
