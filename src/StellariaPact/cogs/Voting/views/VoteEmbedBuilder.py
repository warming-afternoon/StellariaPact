from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import discord

from StellariaPact.cogs.Voting.dto.VoteDetailDto import VoteDetailDto
from StellariaPact.cogs.Voting.dto.VoteStatusDto import VoteStatusDto
from StellariaPact.cogs.Voting.dto.VotingChoicePanelDto import VotingChoicePanelDto
from StellariaPact.cogs.Voting.EligibilityService import EligibilityService
from StellariaPact.cogs.Moderation.dto.ProposalDto import ProposalDto
from StellariaPact.cogs.Moderation.dto.ObjectionDetailsDto import ObjectionDetailsDto


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
        notify_flag: bool,
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
            end_time_ts = int(end_time.replace(tzinfo=ZoneInfo("UTC")).timestamp())
            embed.add_field(
                name="截止时间",
                value=f"<t:{end_time_ts}:F> (<t:{end_time_ts}:R>)",
                inline=False,
            )

        embed.set_footer(
            text=f"投票资格 : 在本帖内有效发言数 ≥ {EligibilityService.REQUIRED_MESSAGES}\n有效发言 : 去除表情后, 长度 ≥ 5"
        )
        return embed

    @staticmethod
    def create_vote_panel_embed(
        topic: str,
        anonymous_flag: bool,
        realtime_flag: bool,
        notify_flag: bool,
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
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        if realtime_flag:
            approve_votes = vote_details.approve_votes if vote_details else 0
            reject_votes = vote_details.reject_votes if vote_details else 0
            embed.add_field(name="赞成", value=str(approve_votes), inline=True)
            embed.add_field(name="反对", value=str(reject_votes), inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)  # Spacer

        if end_time:
            end_time_ts = int(end_time.replace(tzinfo=ZoneInfo("UTC")).timestamp())
            embed.add_field(
                name="截止时间",
                value=f"<t:{end_time_ts}:F> (<t:{end_time_ts}:R>)",
                inline=False,
            )

        embed.set_footer(
            text=f"投票资格 : 在本帖内有效发言数 ≥ {EligibilityService.REQUIRED_MESSAGES}\n有效发言 : 去除表情后, 长度 ≥ 5"
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
            description=f"**{setting_name}** 已被 {changed_by.mention} 切换为 **{new_status}**",
            color=discord.Color.blue(),
        )
        return embed

    @staticmethod
    def create_settings_changed_notification_embed(
        operator: discord.User | discord.Member,
        reason: str,
        new_end_time: Optional[datetime] = None,
        old_end_time: Optional[datetime] = None,
    ) -> discord.Embed:
        """创建一个通用的、用于公示投票设置变更的 Embed。"""
        embed = discord.Embed(
            title="📢 投票设置已更新",
            description=f"{operator.mention} {reason}",
            color=discord.Color.blue(),
        )

        if old_end_time:
            if old_end_time.tzinfo is None:
                old_end_time = old_end_time.replace(tzinfo=ZoneInfo("UTC"))
            old_ts = int(old_end_time.timestamp())
            embed.add_field(
                name="原截止时间", value=f"<t:{old_ts}:F> (<t:{old_ts}:R>)", inline=False
            )

        if new_end_time:
            if new_end_time.tzinfo is None:
                new_end_time = new_end_time.replace(tzinfo=ZoneInfo("UTC"))
            new_ts = int(new_end_time.timestamp())
            embed.add_field(
                name="新的截止时间", value=f"<t:{new_ts}:F> (<t:{new_ts}:R>)", inline=False
            )

        return embed

    @staticmethod
    def build_vote_result_embed(
        topic: str, result: "VoteStatusDto", jump_url: str | None = None
    ) -> discord.Embed:
        """
        构建通用投票结果的 Embed 消息。
        """
        description = None
        if jump_url:
            description = f"\n\n[点击跳转至原投票]({jump_url})"

        embed = discord.Embed(
            title=f"议题「{topic}」的投票已结束",
            description=description,
            color=discord.Color.dark_grey(),
        )

        embed.add_field(name="赞成", value=f"{result.approveVotes}", inline=True)
        embed.add_field(name="反对", value=f"{result.rejectVotes}", inline=True)
        embed.add_field(name="总票数", value=f"{result.totalVotes}", inline=True)

        return embed

    @staticmethod
    def build_voter_list_embeds(
        title: str, voter_ids: list[int], color: discord.Color
    ) -> list[discord.Embed]:
        """
        将一个长的投票者列表分割成多个 Embed。
        """
        embeds = []
        # 每 40 个 ID 创建一个 Embed，以确保不超过字符限制
        chunk_size = 40

        for i in range(0, len(voter_ids), chunk_size):
            chunk = voter_ids[i : i + chunk_size]
            description = "\n".join(f"<@{user_id}>" for user_id in chunk)

            embed = discord.Embed(
                title=f"{title} ({i + 1} - {i + len(chunk)})",
                description=description,
                color=color,
            )
            embeds.append(embed)

        return embeds

    @staticmethod
    def create_management_panel_embed(
        jump_url: str,
        panel_data: VotingChoicePanelDto,
        base_title: str = "投票管理",
        approve_text: str = "✅ 赞成",
        reject_text: str = "❌ 反对",
    ) -> discord.Embed:
        """
        创建统一的、私密的投票管理面板 Embed。
        """

        embed = discord.Embed(
            title=f"对 {jump_url} 的{base_title}",
            color=discord.Color.green() if panel_data.is_eligible else discord.Color.red(),
        )

        embed.add_field(name="当前发言数", value=f"{panel_data.message_count}", inline=True)
        embed.add_field(
            name="要求发言数",
            value=f"≥ {EligibilityService.REQUIRED_MESSAGES}",
            inline=True,
        )
        embed.add_field(
            name="资格状态",
            value="✅ 合格" if panel_data.is_eligible else "❌ 不合格",
            inline=True,
        )

        if panel_data.current_vote_choice is None:
            current_vote_status = "未投票"
        elif panel_data.current_vote_choice == 1:
            current_vote_status = approve_text
        else:
            current_vote_status = reject_text
        embed.add_field(name="当前投票", value=current_vote_status, inline=False)

        if panel_data.is_validation_revoked:
            embed.description = "注意：您的投票资格已被撤销。"

        if not panel_data.is_vote_active:
            embed.add_field(name="投票状态", value="**已结束**", inline=False)
            embed.color = discord.Color.dark_grey()

        return embed

    @staticmethod
    def build_objection_voting_channel_embed(
        objection: ObjectionDetailsDto,
        vote_details: VoteDetailDto,
        thread_jump_url: str
    ) -> discord.Embed:
        """
        为投票频道构建异议裁决的镜像投票面板Embed
        """
        # 描述可以突出显示异议理由
        objection_reason_preview = (objection.objection_reason[:600] + '\n\n...\n\n') if len(objection.objection_reason) > 600 else objection.objection_reason

        embed = discord.Embed(
            title=f"异议裁决投票: {objection.proposal_title}",
            url=thread_jump_url,
            description=f"**异议原因**:\n{objection_reason_preview}",
            color=discord.Color.orange()  # 使用橙色以区分普通投票
        )

        if vote_details.end_time:
            end_time_ts = int(vote_details.end_time.replace(tzinfo=ZoneInfo("UTC")).timestamp())
            embed.add_field(
                name="截止时间",
                value=f"<t:{end_time_ts}:F> (<t:{end_time_ts}:R>)",
                inline=False,
            )

        if vote_details.realtime_flag:
            embed.add_field(name="同意异议", value=str(vote_details.approve_votes), inline=True)
            embed.add_field(name="反对异议", value=str(vote_details.reject_votes), inline=True)
            embed.add_field(name="总票数", value=str(vote_details.total_votes), inline=True)

        embed.set_footer(
            text=f"投票资格 : 在异议讨论帖内有效发言数 ≥ {EligibilityService.REQUIRED_MESSAGES}\n有效发言 : 去除表情后, 长度 ≥ 5"
        )
        return embed

    @staticmethod
    def build_voting_channel_embed(
        proposal: ProposalDto,
        vote_details: VoteDetailDto,
        thread_jump_url: str
    ) -> discord.Embed:
        """
        为投票频道构建镜像投票面板的Embed。
        """
        content_preview = (proposal.content[:600] + '\n\n...\n\n') if len(proposal.content) > 600 else proposal.content

        embed = discord.Embed(
            title=f"{proposal.title}",
            url=f"{thread_jump_url}",
            description=f"{content_preview}",
            color=discord.Color.blue()
        )

        if vote_details.end_time:
            end_time_ts = int(vote_details.end_time.replace(tzinfo=ZoneInfo("UTC")).timestamp())
            embed.add_field(
                name="截止时间",
                value=f"<t:{end_time_ts}:F> (<t:{end_time_ts}:R>)",
                inline=False,
            )

        if vote_details.realtime_flag:
            embed.add_field(name="赞成", value=str(vote_details.approve_votes), inline=True)
            embed.add_field(name="反对", value=str(vote_details.reject_votes), inline=True)
            embed.add_field(name="总票数", value=str(vote_details.total_votes), inline=True)

        embed.set_footer(
            text=f"投票资格 : 在讨论帖内有效发言数 ≥ {EligibilityService.REQUIRED_MESSAGES}\n有效发言 : 去除表情后, 长度 ≥ 5"
        )
        return embed
