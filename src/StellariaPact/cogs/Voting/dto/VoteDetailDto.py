from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class VoterInfo(BaseModel):
    """
    单个投票者的信息
    """

    user_id: int
    choice: int  # 1 for approve, 0 for reject


class VoteDetailDto(BaseModel):
    """
    投票详细状态的数据传输对象
    """

    is_anonymous: bool
    realtime_flag: bool
    notify_flag: bool
    end_time: Optional[datetime]
    context_message_id: Optional[int]
    status: int  # 1 for active, 0 for closed
    total_votes: int
    approve_votes: int
    reject_votes: int
    voters: List[VoterInfo] = []
