from pydantic import BaseModel


class UserActivityDto(BaseModel):
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

    validation: bool
    """用户投票是否有效: 0-无效, 1-有效"""

    class Config:
        from_attributes = True
