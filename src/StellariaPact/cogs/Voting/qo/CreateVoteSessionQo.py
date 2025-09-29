from datetime import datetime
from typing import Optional

from StellariaPact.share.BaseDto import BaseDto


class CreateVoteSessionQo(BaseDto):
    """
    创建投票会话的查询对象
    """

    thread_id: int
    objection_id: Optional[int] = None
    context_message_id: int
    realtime: bool = False
    anonymous: bool = True
    notifyFlag: bool = True
    end_time: Optional[datetime] = None
