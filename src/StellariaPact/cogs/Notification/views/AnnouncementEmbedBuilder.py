from datetime import datetime

import discord


class AnnouncementEmbedBuilder:
    """
    一个专门用于构建公示相关 Embed 和消息内容的静态工具类。
    """

    @staticmethod
    def create_thread_content(
        title: str,
        content: str,
        discord_timestamp: str,
        author: discord.User | discord.Member,
    ) -> str:
        """创建要在讨论帖中发布的主要内容。"""
        return (
            f"{content}\n\n"
            f"**公示截止时间:** {discord_timestamp}\n\n"
            f"*请在此帖内进行讨论*\n"
            f"公示发起人: {author.mention}"
        )

    @staticmethod
    def create_broadcast_embed(
        title: str,
        content: str,
        thread_url: str,
        discord_timestamp: str,
        author: discord.User | discord.Member,
        start_time_utc: datetime,
    ) -> discord.Embed:
        """创建用于广播到其他频道的 Embed。"""
        embed = discord.Embed(
            title=f"📢 新公示: {title}",
            description=f"{content}\n\n[点击此处参与讨论]({thread_url})",
            color=discord.Color.blue(),
            timestamp=start_time_utc,
        )
        embed.set_footer(
            text=f"公示发起人: {author.display_name}",
            icon_url=author.display_avatar.url,
        )
        embed.add_field(name="公示截止时间", value=discord_timestamp, inline=False)
        return embed

    @staticmethod
    def create_repost_embed(
        title: str,
        content: str,
        thread_url: str,
        discord_timestamp: str,
        author: discord.User | discord.Member,
    ) -> discord.Embed:
        """创建用于重复播报的 Embed。"""
        embed = discord.Embed(
            title=f"【公示】 {title}",
            description=f"{content}\n\n[点击此处参与讨论]({thread_url})",
            color=discord.Color.blue(),
        )
        embed.set_footer(
            text=f"公示发起人: {author.display_name}",
            icon_url=author.display_avatar.url,
        )
        embed.add_field(name="公示截止时间", value=discord_timestamp, inline=False)
        return embed

    @staticmethod
    def create_time_modification_embed(
        interaction_user: discord.User | discord.Member,
        operation: str,
        hours: int,
        old_timestamp: str,
        new_timestamp: str,
    ) -> discord.Embed:
        """创建修改公示时间后的通知 Embed。"""
        embed = discord.Embed(
            title="公示时间已更新",
            description=(
                f"{interaction_user.mention} 将公示截止时间 **{operation}** 了 {hours} 小时"
            ),
            color=discord.Color.blue(),
        )
        embed.add_field(name="原截止时间", value=old_timestamp, inline=False)
        embed.add_field(name="新截止时间", value=new_timestamp, inline=False)
        return embed
