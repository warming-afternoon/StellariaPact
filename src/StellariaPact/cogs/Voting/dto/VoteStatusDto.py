from datetime import datetime
from typing import List, Optional

from StellariaPact.cogs.Voting.dto import OptionResult
from StellariaPact.dto import UserVoteDto
from StellariaPact.share import BaseDto


class VoteStatusDto(BaseDto):
    """
    投票状态的数据传输对象，用于封装和传递投票的详细状态信息。
    """

    is_anonymous: bool
    """是否为匿名投票"""

    realtime_flag: bool
    """是否实时显示票数"""

    notify_flag: bool
    """投票结束时是否通知参与者"""

    end_time: Optional[datetime]
    """投票结束时间"""

    status: int
    """投票状态 (0: 已结束, 1: 进行中)"""

    total_votes: int
    """总票数"""

    approve_votes: int
    """赞成票数"""

    reject_votes: int
    """反对票数"""

    options: List[OptionResult] = []
    """各选项的计票结果列表"""

    voters: Optional[List[UserVoteDto]] = []
    """（非匿名投票时）投票者及其选择的列表"""
