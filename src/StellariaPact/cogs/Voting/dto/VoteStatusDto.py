from datetime import datetime
from typing import List, Optional

from StellariaPact.cogs.Voting.dto.OptionResult import OptionResult
from StellariaPact.dto.UserVoteDto import UserVoteDto
from StellariaPact.share.BaseDto import BaseDto


class VoteStatusDto(BaseDto):
    """
    投票状态的数据传输对象。
    """

    is_anonymous: bool
    realtime_flag: bool
    notify_flag: bool
    end_time: Optional[datetime]
    status: int  # 0-已结束, 1-进行中
    totalVotes: int
    approveVotes: int  # 赞成票
    rejectVotes: int  # 反对票
    options: List[OptionResult] = []
    voters: Optional[List[UserVoteDto]] = []
