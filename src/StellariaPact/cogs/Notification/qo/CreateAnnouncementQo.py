from datetime import datetime

from pydantic import BaseModel


class CreateAnnouncementQo(BaseModel):
    """
    创建新公示的查询对象
    """

    discussionThreadId: int
    announcerId: int
    title: str
    content: str
    endTime: datetime
    autoExecute: bool
