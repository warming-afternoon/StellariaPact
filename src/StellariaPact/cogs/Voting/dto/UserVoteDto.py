from datetime import datetime

from pydantic import BaseModel


class UserVoteDto(BaseModel):
    """
    用户投票的数据传输对象。
    """

    id: int
    session_id: int
    user_id: int
    choice: int
    voted_at: datetime

    class Config:
        from_attributes = True
