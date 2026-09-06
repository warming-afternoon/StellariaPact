from dataclasses import dataclass

import discord


@dataclass(slots=True)
class PunishmentPublicityDto:
    """返回正式公示使用的频道、已发送消息或失败说明。"""

    channel: discord.TextChannel | discord.Thread
    """实际发送公示的频道或子区，解锁成功后为接口返回的更新对象。"""

    message: discord.Message | None = None
    """已发送的正式公示消息，解锁或发送失败时为 None。"""

    error: str | None = None
    """供操作者查看的失败及状态恢复说明，发送成功时为 None。"""
