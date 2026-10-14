from dataclasses import dataclass


@dataclass(slots=True)
class ResolvePunishmentPanelQo:
    """传递处罚面板位置及经过控制器验证的旧面板链接。"""

    guild_id: int
    """当前交互所属服务器 ID。"""

    channel_id: int
    """右键选中面板所在的频道或帖子 ID。"""

    message_id: int
    """右键选中面板的消息 ID。"""

    legacy_channel_id: int | None = None
    """临时兼容字段：旧原帖面板中正式公示的频道 ID，过渡期后随 URL 解析一并移除。"""

    legacy_message_id: int | None = None
    """临时兼容字段：旧原帖面板中正式公示的消息 ID，过渡期后随 URL 解析一并移除。"""
