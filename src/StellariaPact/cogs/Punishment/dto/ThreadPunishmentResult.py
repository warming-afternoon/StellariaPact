from dataclasses import dataclass
from datetime import datetime

from StellariaPact.dto.vote_session import VoteDetailDto


@dataclass(slots=True)
class ThreadPunishmentResult:
    """帖子内处罚事务的持久化结果和待刷新的投票面板。"""

    punishment_record_id: int
    """已提交事务中的处罚记录 ID。"""

    vote_details_to_update: list[VoteDetailDto]
    """因投票权变更需要刷新的投票面板快照。"""

    reason: str = ""
    """业务层计算后实际写入的处罚理由。"""

    cumulative_count: int = 0
    """本次处罚提交后的当前累计次数。"""

    voting_allowed: bool = True
    """本次处罚后实际生效的本帖投票权状态。"""

    mute_end_time: datetime | None = None
    """本次处罚后实际生效的禁言截止时间。"""
