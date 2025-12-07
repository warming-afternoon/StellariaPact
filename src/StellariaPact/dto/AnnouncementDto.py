from datetime import datetime

from StellariaPact.share import BaseDto


class AnnouncementDto(BaseDto):
    """
    公示的数据传输对象
    """

    id: int
    discussion_thread_id: int
    announcer_id: int
    title: str
    content: str
    status: int
    end_time: datetime
    auto_execute: bool
