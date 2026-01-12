from datetime import datetime

from pydantic import BaseModel


class UserVoteDto(BaseModel):
    """
    用户投票的数据传输对象。
    """

    id: int
    """主键ID"""

    session_id: int
    """关联的投票会话ID"""

    user_id: int
    """投票用户的Discord ID"""

    choice: int
    """用户的选项: 0-反对, 1-赞成"""

    voted_at: datetime
    """投票时间"""

    class Config:
        from_attributes = True
