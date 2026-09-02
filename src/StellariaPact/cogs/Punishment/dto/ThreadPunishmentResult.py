from dataclasses import dataclass

from StellariaPact.dto.vote_session import VoteDetailDto


@dataclass(slots=True)
class ThreadPunishmentResult:
    """帖子内处罚事务的持久化结果和待刷新的投票面板。"""

    punishment_record_id: int
    vote_details_to_update: list[VoteDetailDto]
