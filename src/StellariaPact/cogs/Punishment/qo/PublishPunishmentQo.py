from dataclasses import dataclass

import discord


@dataclass(slots=True)
class PublishPunishmentQo:
    """传递正式公示的目标频道、展示内容与可选附件。"""

    channel: discord.TextChannel | discord.Thread
    """已通过权限预检的正式公示目标频道或子区。"""

    embed: discord.Embed
    """由视图层构建的正式处罚公示卡片。"""

    files: tuple[discord.File, ...] = ()
    """随正式公示发送的附件，允许为空，资源由调用方负责关闭。"""
