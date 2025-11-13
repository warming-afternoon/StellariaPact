from dataclasses import dataclass, field
from typing import Dict, List

from StellariaPact.cogs.Voting.dto.OptionResult import OptionResult


@dataclass
class VotingChoicePanelDto:
    """
    用于准备投票选择面板的数据传输对象。
    """

    guild_id: int
    thread_id: int
    message_id: int
    is_eligible: bool
    is_vote_active: bool
    message_count: int
    is_validation_revoked: bool
    options: List[OptionResult] = field(default_factory=list)
    # 键是 choice_index, 值是用户的选择 (1 or 0)
    current_votes: Dict[int, int] = field(default_factory=dict)
