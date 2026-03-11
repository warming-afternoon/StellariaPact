from pydantic import BaseModel

from datetime import datetime
from typing import Optional
from StellariaPact.share.BaseDto import BaseDto

class UserActivityDto(BaseDto):
    """
    用户活动的数据传输对象。
    """

    id: int
    """主键ID"""

    user_id: int
    """用户的Discord ID"""

    context_thread_id: int
    """上下文的帖子ID"""

    message_count: int
    """该用户在帖子中的有效发言次数"""

    validation: int
    """用户投票是否有效: 0-无效, 1-有效"""

    mute_end_time: Optional[datetime] = None
    """禁言截止时间"""
