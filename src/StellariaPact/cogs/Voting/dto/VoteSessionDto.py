from datetime import datetime
from typing import Optional

from StellariaPact.share.BaseDto import BaseDto


class VoteSessionDto(BaseDto):
    """
    投票会话的数据传输对象，用于在服务层和视图层之间传递数据。
    """

    id: int
    contextThreadId: int
    objectionId: Optional[int]
    contextMessageId: Optional[int]
    anonymousFlag: bool
    realtimeFlag: bool
    notifyFlag: bool
    status: int
    endTime: Optional[datetime]
