from datetime import datetime
from share.BaseDto import BaseDto

class AnnouncementDto(BaseDto):
    """
    公示的数据传输对象 (Data Transfer Object)
    """
    id: int
    discussionThreadId: int
    title: str
    content: str
    status: int
    endTime: datetime