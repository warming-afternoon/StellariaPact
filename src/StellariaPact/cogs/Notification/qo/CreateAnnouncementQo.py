from datetime import datetime

from pydantic import BaseModel


class CreateAnnouncementQo(BaseModel):
    """
    创建新公示的查询对象
    """

    discussion_thread_id: int
    announcer_id: int
    title: str
    content: str
    end_time: datetime
    auto_execute: bool
