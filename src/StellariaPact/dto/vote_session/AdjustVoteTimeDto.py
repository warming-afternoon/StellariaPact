from datetime import datetime

from pydantic import BaseModel

from StellariaPact.dto import VoteSessionDto


class AdjustVoteTimeDto(BaseModel):
    """
    用于传输调整投票时间操作结果的数据传输对象。
    """

    vote_session: VoteSessionDto
    old_end_time: datetime

    class Config:
        from_attributes = True
