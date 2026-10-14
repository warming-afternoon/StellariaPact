from dataclasses import dataclass


@dataclass(slots=True)
class SavePunishmentPanelQo:
    """传递已经发送成功的处罚面板位置。"""

    record_id: int
    """面板对应的处罚记录 ID。"""

    guild_id: int
    """面板消息所在的服务器 ID。"""

    channel_id: int
    """面板消息所在的频道或帖子 ID。"""

    message_id: int
    """已经发送成功的面板消息 ID。"""

    is_source: bool = False
    """是否为原帖公示，否时保存正式公示位置。"""
