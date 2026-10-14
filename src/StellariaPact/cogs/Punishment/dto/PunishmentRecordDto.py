from datetime import datetime

from StellariaPact.share import BaseDto


class PunishmentRecordDto(BaseDto):
    """表示可在事务结束后用于界面展示的处罚记录快照。"""

    id: int
    """处罚记录的数据库 ID。"""

    guild_id: int
    """处罚所属服务器 ID。"""

    thread_id: int
    """处罚所属提案帖子 ID。"""

    target_user_id: int
    """被处罚用户 ID。"""

    reason: str
    """处罚时记录的理由。"""

    voting_allowed: bool
    """处罚时生效的本帖投票权状态。"""

    mute_end_time: datetime | None
    """处罚时生效的禁言截止时间。"""

    created_at: datetime
    """处罚记录创建时间。"""

    counts_toward_cumulative: bool
    """该记录是否计入累计处罚。"""

    lifted_at: datetime | None
    """解除时间，为空表示未登记解除。"""

    source_message_url: str | None
    """触发处罚的消息链接。"""

    source_publicity_message_id: int | None
    """原帖处罚公示消息 ID。"""

    publicity_guild_id: int | None
    """正式公示所在服务器 ID。"""

    publicity_channel_id: int | None
    """正式公示所在频道或帖子 ID。"""

    publicity_message_id: int | None
    """正式处罚公示消息 ID。"""
