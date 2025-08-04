from datetime import datetime
from typing import Optional

import discord
from zoneinfo import ZoneInfo

from StellariaPact.cogs.Voting.dto.VoteDetailDto import VoteDetailDto
from StellariaPact.cogs.Voting.EligibilityService import EligibilityService


class VoteEmbedBuilder:
    """
    一个构建器类，负责创建和更新与投票相关的 discord.Embed 对象。
    这确保了视图渲染逻辑与业务逻辑的分离。
    """

    @staticmethod
    def create_initial_vote_embed(
        topic: str,
        author: Optional[discord.User | discord.Member],
        realtime: bool,
        anonymous: bool,
        end_time: Optional[datetime] = None,
    ) -> discord.Embed:
        """
        创建投票初始状态的 Embed 面板。
        """
        description = "点击下方按钮，对本提案进行投票。"
        # if author:
        #     description = f"由 {author.mention} 发起的投票已开始！\n请点击下方按钮参与。"

        embed = discord.Embed(
            title=f"议题：{topic}",
            description=description,
            color=discord.Color.blue(),
        )
        embed.add_field(name="是否匿名", value="✅ 是" if anonymous else "❌ 否", inline=True)
        embed.add_field(name="实时票数", value="✅ 是" if realtime else "❌ 否", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        if realtime:
            embed.add_field(name="赞成", value="0", inline=True)
            embed.add_field(name="反对", value="0", inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)

        if end_time:
            embed.add_field(
                name="截止时间",
                value=f"<t:{int(end_time.replace(tzinfo=ZoneInfo('UTC')).timestamp())}:F>",
                inline=False,
            )

        embed.set_footer(
            text=f"投票资格：在本帖内有效发言数 ≥ {EligibilityService.REQUIRED_MESSAGES}"
        )
        return embed

    @staticmethod
    def create_vote_panel_embed(
        topic: str,
        anonymous_flag: bool,
        realtime_flag: bool,
        end_time: Optional[datetime],
        vote_details: Optional[VoteDetailDto] = None,
    ) -> discord.Embed:
        """
        根据明确的数据构建主投票面板 Embed，实现视图和数据的解耦。
        """
        description = "点击下方按钮，对本提案进行投票。"
        embed = discord.Embed(
            title=f"议题：{topic}",
            description=description,
            color=discord.Color.blue(),
        )
        embed.add_field(name="是否匿名", value="✅ 是" if anonymous_flag else "❌ 否", inline=True)
        embed.add_field(name="实时票数", value="✅ 是" if realtime_flag else "❌ 否", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # Spacer

        if realtime_flag:
            approve_votes = vote_details.approve_votes if vote_details else 0
            reject_votes = vote_details.reject_votes if vote_details else 0
            embed.add_field(name="赞成", value=str(approve_votes), inline=True)
            embed.add_field(name="反对", value=str(reject_votes), inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)  # Spacer

        if end_time:
            embed.add_field(
                name="截止时间",
                value=f"<t:{int(end_time.replace(tzinfo=ZoneInfo('UTC')).timestamp())}:F>",
                inline=False,
            )

        embed.set_footer(
            text=f"投票资格：在本帖内有效发言数 ≥ {EligibilityService.REQUIRED_MESSAGES}"
        )
        return embed

    @staticmethod
    def update_vote_counts_embed(
        original_embed: discord.Embed, vote_details: VoteDetailDto
    ) -> discord.Embed:
        """
        根据最新的投票数据更新现有的 Embed 对象。

        :param original_embed: 要更新的原始 Embed 对象。
        :param vote_details: 包含最新投票计数和状态的 DTO。
        :return: 更新后的 Embed 对象。
        """
        # 克隆原始 embed 以避免直接修改
        embed = original_embed.copy()

        if vote_details.realtime_flag and len(embed.fields) >= 5:
            embed.set_field_at(
                3,
                name="赞成",
                value=str(vote_details.approve_votes),
                inline=True,
            )
            embed.set_field_at(4, name="反对", value=str(vote_details.reject_votes), inline=True)

        return embed

    @staticmethod
    def create_time_adjustment_embed(
        operator: discord.User | discord.Member,
        hours: int,
        old_time: datetime,
        new_time: datetime,
    ) -> discord.Embed:
        """
        创建公示投票时间变更的 Embed。
        """
        operation_text = "延长" if hours > 0 else "缩短"
        abs_hours = abs(hours)

        embed = discord.Embed(
            title="投票时间已更新",
            description=(
                f"{operator.mention} 将投票截止时间 **{operation_text}** 了 {abs_hours} 小时。"
            ),
            color=discord.Color.blue(),
        )

        # 确保时间都是 UTC 时区感知的
        if old_time.tzinfo is None:
            old_time = old_time.replace(tzinfo=ZoneInfo("UTC"))
        if new_time.tzinfo is None:
            new_time = new_time.replace(tzinfo=ZoneInfo("UTC"))

        embed.add_field(
            name="原截止时间",
            value=f"<t:{int(old_time.timestamp())}:F>",
            inline=False,
        )
        embed.add_field(
            name="新截止时间",
            value=f"<t:{int(new_time.timestamp())}:F>",
            inline=False,
        )

        return embed

    @staticmethod
    def create_confirmation_embed(title: str, description: str) -> discord.Embed:
        """创建一个通用的、用于二次确认的 Embed。"""
        return discord.Embed(
            title=title,
            description=description,
            color=discord.Color.orange(),
        )

    @staticmethod
    def create_setting_changed_embed(
        changed_by: discord.User | discord.Member,
        setting_name: str,
        new_status: str,
    ) -> discord.Embed:
        """创建一个公开通示，告知某项设置已被更改。"""
        embed = discord.Embed(
            title="投票设置已更新",
            description=f"**{setting_name}** 已被 {changed_by.mention} 切换为 **{new_status}**。",
            color=discord.Color.blue(),
        )
        return embed
