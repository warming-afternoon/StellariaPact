from dataclasses import dataclass

import discord


@dataclass(slots=True)
class PublicityChannelDto:
    """返回通过权限预检的公示频道或需要降级的原因。"""

    channel: discord.TextChannel | discord.Thread | None = None
    """通过权限预检的公示频道或子区，不可用时为 None。"""

    fallback_reason: str | None = None
    """公示区不可用时的降级原因，可正常发送时为 None。"""
