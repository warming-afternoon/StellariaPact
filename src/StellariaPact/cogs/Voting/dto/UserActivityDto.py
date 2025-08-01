from pydantic import BaseModel


class UserActivityDto(BaseModel):
    """
    用户活动的数据传输对象。
    """

    id: int
    userId: int
    contextThreadId: int
    messageCount: int
    validation: bool

    class Config:
        from_attributes = True
