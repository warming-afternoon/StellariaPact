from datetime import datetime

import discord
from zoneinfo import ZoneInfo


class ModerationEmbedBuilder:
    """
    构建议事管理相关操作的 Embed 消息。
    """

    @staticmethod
    def create_kick_embed(
        moderator: discord.Member,
        kicked_user: discord.User | discord.Member,
        reason: str,
        target_message: discord.Message,
    ) -> discord.Embed:
        """
        创建踢出提案的处罚公示 Embed。
        """
        embed = discord.Embed(
            title="议事成员资格变动公示",
            description=f"**目标用户**: {kicked_user.mention}\n**处理方式**: 剥夺本帖议事资格",
            color=discord.Color.red(),
            timestamp=datetime.now(ZoneInfo("UTC")),
        )
        embed.add_field(name="处理理由", value=reason, inline=False)
        embed.add_field(
            name="相关消息", value=f"[点击跳转]({target_message.jump_url})", inline=True
        )
        embed.add_field(name="操作人员", value=moderator.mention, inline=True)
        return embed
