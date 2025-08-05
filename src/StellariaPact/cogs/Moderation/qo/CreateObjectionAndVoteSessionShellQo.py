from dataclasses import dataclass

from StellariaPact.share.enums.ObjectionStatus import ObjectionStatus


@dataclass
class CreateObjectionAndVoteSessionShellQo:
    """
    创建异议和投票会话“空壳”的查询对象。
    """

    proposal_id: int
    objector_id: int
    reason: str
    required_votes: int
    status: ObjectionStatus
    thread_id: int
    is_anonymous: bool
    is_realtime: bool
