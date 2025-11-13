from datetime import datetime
from typing import Optional

from ....share.BaseDto import BaseDto
from ....share.enums.ObjectionStatus import ObjectionStatus


class CreateObjectionAndVoteSessionShellQo(BaseDto):
    """
    创建异议和投票会话"空壳"的查询对象。
    """

    guild_id: int
    proposal_id: int
    objector_id: int
    reason: str
    required_votes: int
    status: ObjectionStatus
    thread_id: int
    is_anonymous: bool
    is_realtime: bool
    end_time: Optional[datetime] = None
