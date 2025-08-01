from datetime import datetime

from StellariaPact.models.VoteSession import VoteSession
from StellariaPact.share.BaseDto import BaseDto


class AdjustVoteTimeDto(BaseDto):
    """
    用于传输调整投票时间操作结果的数据传输对象。
    """

    vote_session: VoteSession
    old_end_time: datetime
