from pydantic import BaseModel


class UserActivityDto(BaseModel):
    """
    用户活动的数据传输对象。
    """

    id: int
    user_id: int
    context_thread_id: int
    message_count: int
    validation: bool

    class Config:
        from_attributes = True
