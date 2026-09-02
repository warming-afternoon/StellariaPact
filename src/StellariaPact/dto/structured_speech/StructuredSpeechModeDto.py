from StellariaPact.share import BaseDto


class StructuredSpeechModeDto(BaseDto):
    """表示可安全跨会话传递的模板发言模式快照。"""

    thread_id: int
    """表示启用模板发言模式的讨论帖子 ID。"""

    forum_id: int
    """表示讨论帖子所属的父论坛频道 ID。"""

    interval_seconds: int
    """表示普通用户通过 Bot 发言的间隔秒数。"""

    proposer_cooldown_exempt: bool = True
    """表示提案主是否豁免通过 Bot 发言的时间间隔。"""

    previous_slowmode_delay: int
    """表示开启模式前保存的帖子慢速模式秒数。"""
