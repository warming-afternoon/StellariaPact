from datetime import datetime
from typing import Optional

import discord


class PunishmentEmbedBuilder:
    @staticmethod
    def create_punishment_embed(
        moderator: discord.Member,
        target_user: discord.User | discord.Member,
        reason: str,
        target_message: Optional[discord.Message],
        is_voting_allowed: bool,
        mute_end_time: Optional[datetime] = None,
    ) -> discord.Embed:
        """创建处罚公示 Embed"""
        description_lines = [f"**目标用户**: {target_user.mention}"]

        if is_voting_allowed:
            description_lines.append("**处理方式**:\n保留本帖投票资格")
            color = discord.Color.orange()
        else:
            description_lines.append("**处理方式**:\n剥夺本帖投票资格")
            color = discord.Color.red()

        if mute_end_time:
            ts = int(mute_end_time.timestamp())
            description_lines.append(f"**禁言至**: <t:{ts}:F> (<t:{ts}:R>)")
        else:
            description_lines.append("**禁言状态**: 无禁言 / 已解除")

        embed = discord.Embed(
            title="议事成员资格及处罚变动公示",
            description="\n".join(description_lines),
            color=color,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="处理理由", value=reason, inline=False)

        if target_message:
            embed.add_field(
                name="触发消息",
                value=f"[点击跳转]({target_message.jump_url})",
                inline=True,
            )

        embed.add_field(name="操作人员", value=moderator.mention, inline=True)
        return embed

    @staticmethod
    def create_unpunish_embed(
        moderator: discord.Member,
        target_user: discord.User | discord.Member,
        reason: str,
    ) -> discord.Embed:
        """创建解除处罚的公示 Embed"""
        embed = discord.Embed(
            title="议事成员处罚解除公示",
            description=(
                f"**目标用户**: {target_user.mention}\n"
                f"**处理方式**: 恢复本帖投票资格，并解除禁言限制。"
            ),
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="解除理由", value=reason, inline=False)
        embed.add_field(name="操作人员", value=moderator.mention, inline=True)
        return embed
