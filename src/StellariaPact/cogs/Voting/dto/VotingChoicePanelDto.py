from dataclasses import dataclass
from typing import Optional


@dataclass
class VotingChoicePanelDto:
    """
    用于准备投票选择面板的数据传输对象。
    """

    is_eligible: bool
    is_vote_active: bool
    message_count: int
    current_vote_choice: Optional[int]  # 1 for approve, 0 for reject, None for not voted
    is_validation_revoked: bool