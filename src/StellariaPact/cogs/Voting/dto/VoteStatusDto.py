from datetime import datetime
from typing import Optional

from StellariaPact.share.BaseDto import BaseDto


class VoteStatusDto(BaseDto):
    """
    投票状态的数据传输对象。
    """

    is_anonymous: bool
    end_time: Optional[datetime]
    status: int  # 0-已结束, 1-进行中
    totalVotes: int
    approveVotes: int  # 赞成票
    rejectVotes: int  # 反对票
