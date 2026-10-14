from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(slots=True)
class ApplyThreadPunishmentQo:
    """传递帖子处罚的目标、操作人和处罚设置。"""

    guild_id: int
    """处罚所属服务器 ID。"""

    thread_id: int
    """处罚所属提案帖子 ID。"""

    target_user_id: int
    """被处罚用户的真实 Discord ID。"""

    moderator_id: int
    """执行处罚的管理员 ID。"""

    reason: str
    """人工处罚理由，快速处罚由业务层生成固定理由。"""

    source_message_url: str | None
    """触发处罚的原始消息链接。"""

    voting_allowed: bool
    """人工处罚后是否保留投票权。"""

    mute_end_time: datetime | None
    """人工处罚的禁言截止时间，快速处罚由业务层计算。"""

    quick_mode: Literal["cumulative", "off_topic"] | None = None
    """快速处罚类型，为空时使用人工处罚设置。"""

    off_topic_confirmed: bool = False
    """管理员是否已确认在有累计记录时继续歪楼滑坡处罚。"""
