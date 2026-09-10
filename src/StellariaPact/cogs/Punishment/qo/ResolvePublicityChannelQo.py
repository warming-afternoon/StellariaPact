from dataclasses import dataclass

import discord


@dataclass(slots=True)
class ResolvePublicityChannelQo:
    """传递处罚公示频道解析所需的服务器上下文。"""

    guild: discord.Guild
    """处罚所在的 Discord 服务器，用于频道查询和机器人权限预检。"""
