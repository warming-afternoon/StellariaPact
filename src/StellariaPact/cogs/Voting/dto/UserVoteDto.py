from datetime import datetime

from pydantic import BaseModel


class UserVoteDto(BaseModel):
    """
    用户投票的数据传输对象。
    """

    id: int
    sessionId: int
    userId: int
    choice: int
    votedAt: datetime

    class Config:
        from_attributes = True
