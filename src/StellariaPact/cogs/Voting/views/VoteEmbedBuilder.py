from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import discord

from StellariaPact.cogs.Voting.dto import OptionResult, VoteDetailDto, VotingChoicePanelDto
from StellariaPact.cogs.Voting.EligibilityService import EligibilityService
from StellariaPact.dto import ObjectionDetailsDto, ProposalDto

logger = logging.getLogger(__name__)


class VoteEmbedBuilder:
    """
    一个构建器类，负责创建和更新与投票相关的 discord.Embed 对象
    """

    @staticmethod
    def _add_vote_options_fields(
        embed: discord.Embed,
        vote_details: VoteDetailDto,
        approve_text: str = "赞成",
        reject_text: str = "反对",
    ):
        """
        向 Embed 添加投票选项和结果字段。
        """
        if vote_details.options:
            for i, option in enumerate(vote_details.options, 1):
                # 显示选项标题和文本
                embed.add_field(
                    name=f"**选项 {i} : {option.choice_text}**",
                    value="",
                    inline=False,
                )
                if vote_details.realtime_flag:
                    # 显示票数统计
                    embed.add_field(
                        name=approve_text,
                        value=str(option.approve_votes),
                        inline=True,
                    )
                    embed.add_field(
                        name=reject_text,
                        value=str(option.reject_votes),
                        inline=True,
                    )
                    embed.add_field(
                        name="\u200b",
                        value="\u200b",
                        inline=True,
                    )
        elif vote_details.realtime_flag:
            # 如果没有 options 但启用了实时票数，显示总票数统计
            embed.add_field(
                name=approve_text, value=str(vote_details.total_approve_votes), inline=True
            )
            embed.add_field(
                name=reject_text, value=str(vote_details.total_reject_votes), inline=True
            )
            embed.add_field(name="\u200b", value="\u200b", inline=True)

    @staticmethod
    def _add_end_time_field(embed: discord.Embed, end_time: Optional[datetime]):
        """
        向 Embed 添加截止时间字段。
        """
        if end_time:
            end_time_ts = int(end_time.replace(tzinfo=ZoneInfo("UTC")).timestamp())
            embed.add_field(
                name="截止时间",
                value=f"<t:{end_time_ts}:F> (<t:{end_time_ts}:R>)",
                inline=False,
            )

    @staticmethod
    def create_vote_panel_embed(
        topic: str,
        anonymous_flag: bool,
        realtime_flag: bool,
        notify_flag: bool,
        end_time: Optional[datetime],
        vote_details: VoteDetailDto,
    ) -> discord.Embed:
        """
        构建主投票面板 Embed
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

        VoteEmbedBuilder._add_vote_options_fields(embed, vote_details)
        VoteEmbedBuilder._add_end_time_field(embed, end_time)

        embed.set_footer(
            text=f"投票资格 : 在本帖内有效发言数 ≥ {EligibilityService.REQUIRED_MESSAGES}\n"
            f"有效发言 : 去除表情后, 长度 ≥ 5"
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
    def build_vote_result_embeds(
        topic: str, result: VoteDetailDto, jump_url: str | None = None
    ) -> list[discord.Embed]:
        """
        构建通用投票结果的 Embed 消息列表。
        第一个是普通投票embed，如果有异议投票，则追加第二个异议投票结果embed。
        """
        embeds = []
        description = None
        if jump_url:
            description = f"[点击跳转至原投票]({jump_url})"

        # --- 普通投票 Embed ---
        normal_embed = discord.Embed(
            title=f"议题「{topic}」的投票已结束",
            description=description,
            color=discord.Color.dark_green(),
        )

        normal_options = result.normal_options if result.normal_options else result.options
        if normal_options:
            for i, option in enumerate(normal_options, 1):
                normal_embed.add_field(
                    name=f"**选项 {option.choice_index} : {option.choice_text}**",
                    value="",
                    inline=False,
                )
                normal_embed.add_field(name="赞成", value=str(option.approve_votes), inline=True)
                normal_embed.add_field(name="反对", value=str(option.reject_votes), inline=True)
                normal_embed.add_field(name="总票数", value=str(option.total_votes), inline=True)
        else:
            normal_embed.add_field(name="赞成", value=f"{result.total_approve_votes}", inline=True)
            normal_embed.add_field(name="反对", value=f"{result.total_reject_votes}", inline=True)
            normal_embed.add_field(name="总票数", value=f"{result.total_votes}", inline=True)

        embeds.append(normal_embed)

        # --- 异议投票 Embed ---
        if result.objection_options:
            objection_embed = discord.Embed(
                title=f"议题「{topic}」的异议投票已结束",
                color=discord.Color.orange(),
            )
            for option in result.objection_options:
                objection_embed.add_field(
                    name=f"**异议 {option.choice_index} : {option.choice_text}**",
                    value="",
                    inline=False,
                )
                objection_embed.add_field(name="赞成异议", value=str(option.approve_votes), inline=True)
                objection_embed.add_field(name="反对异议", value=str(option.reject_votes), inline=True)
                objection_embed.add_field(name="总票数", value=str(option.total_votes), inline=True)

            embeds.append(objection_embed)

        return embeds

    @staticmethod
    def build_voter_list_embeds_from_details(result: VoteDetailDto) -> list[discord.Embed]:
        """
        从 VoteDetailDto 构建详细的实名投票者名单 Embed 列表，支持按不同选项划分。
        """
        embeds = []
        if result.is_anonymous or not result.voters:
            return embeds

        # 按 (option_type, choice_index, choice) 分组记录 voter_id
        # option_type: 0-普通, 1-异议 | choice: 1-赞成, 0-反对
        groups = {}
        for v in result.voters:
            key = (v.option_type, v.choice_index, v.choice)
            if key not in groups:
                groups[key] = []
            groups[key].append(v.user_id)

        # 辅助获取选项文本的方法
        def get_option_text(opt_type, idx):
            if opt_type == 0:
                opts = result.normal_options if result.normal_options else result.options
                prefix = "选项"
            else:
                opts = result.objection_options
                prefix = "异议"

            for o in opts:
                if o.choice_index == idx:
                    return f"{prefix} {idx}: {o.choice_text}"
            return f"{prefix} {idx}"

        # 遍历所有存在票数的选项群组
        for (opt_type, idx, choice), user_ids in sorted(groups.items()):
            choice_str = "赞成" if choice == 1 else "反对"
            color = discord.Color.green() if choice == 1 else discord.Color.red()
            opt_text = get_option_text(opt_type, idx)

            title = f"{choice_str}名单 - {opt_text}"

            # 分块以避开 Discord 字符限制
            chunk_size = 40
            for i in range(0, len(user_ids), chunk_size):
                chunk = user_ids[i : i + chunk_size]
                description = "\n".join(f"<@{user_id}>" for user_id in chunk)
                page_title = title if len(user_ids) <= chunk_size else f"{title} ({i + 1} - {i + len(chunk)})"

                embed = discord.Embed(
                    title=page_title,
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

        if panel_data.options:
            # 为每个选项显示选项文本和用户的选择
            for i, option in enumerate(panel_data.options, 1):
                # 用户的选择
                user_choice = panel_data.current_votes.get(option.choice_index)
                if user_choice is None:
                    status = "未投票"
                elif user_choice == 1:
                    status = approve_text
                else:
                    status = reject_text

                # 显示选项文本
                embed.add_field(
                    name=f"选项 {i} : ( {status} )",
                    value=option.choice_text,
                    inline=False,
                )
        else:
            # 如果没有选项，显示用户的投票状态
            user_choice = panel_data.current_votes.get(1)  # 默认检查选项1
            if user_choice is None:
                status = "未投票"
            elif user_choice == 1:
                status = approve_text
            else:
                status = reject_text
            embed.add_field(name="当前投票", value=status, inline=False)

        if panel_data.is_validation_revoked:
            embed.description = "注意：您的投票资格已被撤销。"

        if not panel_data.is_vote_active:
            embed.add_field(name="投票状态", value="**已结束**", inline=False)
            embed.color = discord.Color.dark_grey()

        return embed

    @staticmethod
    def create_new_option_notification_embed(
        creator: discord.User | discord.Member,
        option_type: int,
        option_text: str
    ) -> discord.Embed:
        """创建一个通知贴内所有人有新选项/异议被添加的 Embed。"""
        option_type_name = "普通投票选项" if option_type == 0 else "异议选项"
        color = discord.Color.green() if option_type == 0 else discord.Color.orange()

        embed = discord.Embed(
            title=f"新增{option_type_name}",
            description=f"> 创建人 : {creator.mention} \n\n{option_text}",
            color=color,
        )
        return embed

    @staticmethod
    def build_objection_voting_channel_embed(
        objection: ObjectionDetailsDto, vote_details: VoteDetailDto, thread_jump_url: str
    ) -> discord.Embed:
        """
        为投票频道构建异议裁决的镜像投票面板Embed
        """
        # 描述可以突出显示异议理由
        objection_reason_preview = (
            (objection.objection_reason[:600] + "\n\n...\n\n")
            if len(objection.objection_reason) > 600
            else objection.objection_reason
        )

        embed = discord.Embed(
            title=f"异议裁决投票: {objection.proposal_title}",
            url=thread_jump_url,
            description=f"**异议原因**:\n{objection_reason_preview}",
            color=discord.Color.orange(),  # 使用橙色以区分普通投票
        )

        VoteEmbedBuilder._add_end_time_field(embed, vote_details.end_time)

        VoteEmbedBuilder._add_vote_options_fields(
            embed, vote_details, approve_text="同意异议", reject_text="反对异议"
        )

        embed.set_footer(
            text=f"投票资格 : 在异议讨论帖内有效发言数 ≥ {EligibilityService.REQUIRED_MESSAGES}\n"
            f"有效发言 : 去除表情后, 长度 ≥ 5"
        )
        return embed

    @staticmethod
    def build_voting_channel_embed(
        proposal: ProposalDto, vote_details: VoteDetailDto, thread_jump_url: str
    ) -> list[discord.Embed]:
        """
        为投票频道构建三段式镜像投票面板 Embed：
         1. 提案内容（固定第一个）
         2. 普通投票（固定第二个）
         3. 异议投票（仅在存在异议选项时追加）
        """
        embeds: list[discord.Embed] = []

        # --- 提案内容 Embed---
        description = (
            (proposal.content[:600] + "\n\n...\n\n") if len(proposal.content) > 600 else proposal.content
        )
        proposal_embed = discord.Embed(
            title=f"{proposal.title}",
            url=f"{thread_jump_url}",
            description=description,
            color=discord.Color.blue(),
        )
        VoteEmbedBuilder._add_end_time_field(proposal_embed, vote_details.end_time)
        proposal_embed.set_footer(
            text=f"投票资格 : 点击标题，在跳转到的讨论帖内有效发言数 ≥"
            f" {EligibilityService.REQUIRED_MESSAGES}\n有效发言 : 去除表情后, 长度 ≥ 5"
        )
        embeds.append(proposal_embed)

        # --- 普通投票 Embed---
        normal_options = vote_details.normal_options
        if not normal_options and not vote_details.objection_options:
            # 兼容旧数据：若未拆分类型且不存在异议选项，回退使用扁平 options
            normal_options = vote_details.options

        normal_embed = discord.Embed(
            title="普通投票",
            color=discord.Color.green(),
        )
        if normal_options:
            for opt in normal_options:
                if vote_details.realtime_flag:
                    value = f"✅ 赞成: {opt.approve_votes} | ❌ 反对: {opt.reject_votes}"
                else:
                    value = "隐藏"
                normal_embed.add_field(
                    name=f"选项 {opt.choice_index}: \n{opt.choice_text}\n",
                    value=value,
                    inline=False,
                )
        else:
            normal_embed.description = "暂无选项"
            if vote_details.realtime_flag:
                normal_embed.add_field(
                    name="总赞成票",
                    value=str(vote_details.total_approve_votes),
                    inline=True,
                )
                normal_embed.add_field(
                    name="总反对票",
                    value=str(vote_details.total_reject_votes),
                    inline=True,
                )
                normal_embed.add_field(
                    name="总票数",
                    value=str(vote_details.total_votes),
                    inline=True,
                )
        embeds.append(normal_embed)

        # --- 异议投票 Embed（仅在存在异议选项时追加）---
        objection_options = vote_details.objection_options
        if objection_options:
            objection_embed = discord.Embed(
                title="异议投票",
                color=discord.Color.orange(),
            )
            for opt in objection_options:
                if vote_details.realtime_flag:
                    value = f"✅ 赞成异议: {opt.approve_votes} | ❌ 反对异议: {opt.reject_votes}"
                else:
                    value = ""
                objection_embed.add_field(
                    name=f"异议 {opt.choice_index}: {opt.choice_text}",
                    value=value,
                    inline=False,
                )
            embeds.append(objection_embed)

        return embeds

    @staticmethod
    def create_vote_panel_embed_v2(topic: str, vote_details: VoteDetailDto) -> list[discord.Embed]:
        """
        构建新的三段式投票面板 Embed，返回最多三个独立的 Embed：
         1. 投票规则（固定第一个）
         2. 普通投票（固定第二个）
         3. 异议投票（仅在存在异议选项时追加）
        """
        embeds = []

        # --- 投票规则 Embed ---
        rule_embed = discord.Embed(
            title=f"议题：{topic}",
            description="",
            color=discord.Color.blue(),
        )
        rule_embed.add_field(name="是否匿名", value="✅ 是" if vote_details.is_anonymous else "❌ 否", inline=True)
        rule_embed.add_field(name="实时票数", value="✅ 是" if vote_details.realtime_flag else "❌ 否", inline=True)
        rule_embed.add_field(name="\u200b", value="\u200b", inline=True)  # 占位

        if vote_details.end_time:
            end_ts = int(vote_details.end_time.timestamp())
            rule_embed.add_field(
                name="截止时间",
                value=f"<t:{end_ts}:F> (<t:{end_ts}:R>)",
                inline=False,
            )
        else:
            rule_embed.add_field(name="截止时间", value="手动结束", inline=False)

        rule_embed.set_footer(
            text=f"投票资格 : 点击标题，在跳转到的讨论帖内有效发言数 ≥"
            f" {EligibilityService.REQUIRED_MESSAGES}\n有效发言 : 去除表情后, 长度 ≥ 5"
        )
        embeds.append(rule_embed)

        # --- 普通投票 Embed ---
        # 普通选项来源：优先使用 normal_options，回退到 options
        normal_options = vote_details.normal_options if vote_details.normal_options else vote_details.options
        if normal_options:
            normal_embed = discord.Embed(
                title="普通投票",
                color=discord.Color.green(),
            )
            for opt in normal_options:
                if vote_details.realtime_flag:
                    val = f"✅ 赞成: {opt.approve_votes} | ❌ 反对: {opt.reject_votes}"
                else:
                    val = ""
                normal_embed.add_field(
                    name=f"选项 {opt.choice_index}: ",
                    value=f"\n\n{opt.choice_text}\n"+val+"\n",
                    inline=False,
                )
            embeds.append(normal_embed)
        else:
            # 没有普通选项时，显示总票数汇总
            normal_embed = discord.Embed(
                title="普通投票",
                description="暂无选项",
                color=discord.Color.green(),
            )
            if vote_details.realtime_flag:
                normal_embed.add_field(
                    name="总赞成票",
                    value=str(vote_details.total_approve_votes),
                    inline=True,
                )
                normal_embed.add_field(
                    name="总反对票",
                    value=str(vote_details.total_reject_votes),
                    inline=True,
                )
                normal_embed.add_field(
                    name="总票数",
                    value=str(vote_details.total_votes),
                    inline=True,
                )
            embeds.append(normal_embed)

        # --- 异议投票 Embed（仅在存在异议选项时追加）---
        objection_options = vote_details.objection_options
        if objection_options:
            objection_embed = discord.Embed(
                title="异议投票",
                color=discord.Color.orange(),
            )
            for opt in objection_options:
                if vote_details.realtime_flag:
                    val = f"✅ 赞成异议: {opt.approve_votes} | ❌ 反对异议: {opt.reject_votes}"
                else:
                    val = "隐藏"
                objection_embed.add_field(
                    name=f"异议 {opt.choice_index}: {opt.choice_text}",
                    value=val,
                    inline=False,
                )
            embeds.append(objection_embed)

        return embeds

    @staticmethod
    def build_paginated_manage_embed(
        jump_url: str,
        option_type: int,
        options: list[OptionResult],
        realtime_flag: bool,
    ) -> discord.Embed:
        """
        构建分页管理视图的 Embed。
        依次显示每个投票选项的投票选项内容。
        若 realtime_flag == True，则在每个选项内容下方显示其对应的票数。
        """
        summary = "普通投票" if option_type == 0 else "异议投票"
        title = f"对 {jump_url} 的" + summary
        embed = discord.Embed(title=title, description="", color=discord.Color.blurple())

        # 依次显示每个选项内容
        for i, opt in enumerate(options, 1):
            # 显示选项标题和文本
            embed.add_field(
                name=f"**选项 {i}** :",
                value=f"{opt.choice_text}",
                inline=False,
            )
            if realtime_flag:
                # 显示票数统计
                embed.add_field(
                    name="赞成",
                    value=str(opt.approve_votes),
                    inline=True,
                )
                embed.add_field(
                    name="反对",
                    value=str(opt.reject_votes),
                    inline=True,
                )
                embed.add_field(
                    name="总票数",
                    value=str(opt.total_votes),
                    inline=True,
                )

        return embed
