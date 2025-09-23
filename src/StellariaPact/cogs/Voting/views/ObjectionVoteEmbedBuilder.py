from datetime import datetime
from typing import Optional

import discord

from StellariaPact.cogs.Moderation.dto.HandleSupportObjectionResultDto import (
    HandleSupportObjectionResultDto,
)
from StellariaPact.cogs.Moderation.dto.ObjectionDetailsDto import ObjectionDetailsDto
from StellariaPact.cogs.Voting.dto.VoteDetailDto import VoteDetailDto
from StellariaPact.cogs.Voting.EligibilityService import EligibilityService
from StellariaPact.cogs.Voting.qo.BuildFirstObjectionEmbedQo import BuildFirstObjectionEmbedQo


class ObjectionVoteEmbedBuilder:
    """
    一个专门用于构建异议投票相关 Embed 的类。
    """

    @staticmethod
    def build_first_objection_embed(
        qo: "BuildFirstObjectionEmbedQo",
    ) -> discord.Embed:
        """
        构建首次异议的 Embed 消息，用于发起投票。
        """
        embed = discord.Embed(
            title="异议产生票收集中",
            description=(
                f"对提案 [{qo.proposal_title}]({qo.proposal_url}) 的一项异议"
                "需要收集足够的支持票以进入正式讨论阶段。\n\n"
                f"**异议发起人**: <@{qo.objector_id}> ({qo.objector_display_name})"
            ),
            color=discord.Color.yellow(),
        )
        embed.add_field(name="异议理由", value=f"{qo.objection_reason}", inline=False)
        embed.add_field(name="所需票数", value=str(qo.required_votes), inline=True)
        embed.add_field(name="当前支持", value=f"0 / {qo.required_votes}", inline=True)
        return embed

    @staticmethod
    def create_formal_embed(
        objection_dto: ObjectionDetailsDto, end_time: Optional[datetime] = None
    ) -> discord.Embed:
        """
        创建正式异议投票的初始 Embed。

        :param objection_dto: 包含异议和提案信息的DTO。
        :param end_time: 投票的结束时间。
        :return: 一个 discord.Embed 对象。
        """
        embed = discord.Embed(
            title="裁决投票：是否同意此异议？",
            description=f"此投票用于裁决由 <@{objection_dto.objector_id}> 发起的，"
            f"针对提案 **「{objection_dto.proposal_title}」** 的异议。",
            color=discord.Color.orange(),
        )

        embed.add_field(
            name="投票规则",
            value="请议事成员进行投票。\n如果“赞成异议”票数超过“反对异议”票数，则原提案将被推翻",
            inline=False,
        )
        embed.add_field(name="✅ 同意异议", value="**0**", inline=True)
        embed.add_field(name="❌ 反对异议", value="**0**", inline=True)

        if end_time:
            embed.add_field(
                name="截止时间",
                value=f"<t:{int(end_time.timestamp())}:f> (<t:{int(end_time.timestamp())}:R>)",
                inline=False,
            )

        embed.set_footer(
            text=f"投票资格 : 在本帖内有效发言数 ≥ {EligibilityService.REQUIRED_MESSAGES}\n有效发言 : 去除表情后, 长度 ≥ 5"
        )

        return embed

    @staticmethod
    def update_support_embed(
        original_embed: discord.Embed,
        result_dto: HandleSupportObjectionResultDto,
        guild_id: int,
    ) -> discord.Embed:
        """
        更新异议支持收集面板。
        """
        new_embed = original_embed.copy()

        # 重构描述以保留链接
        proposal_url = (
            f"https://discord.com/channels/{guild_id}/{result_dto.proposal_discussion_thread_id}"
        )
        new_embed.description = (
            f"对提案 **[{result_dto.proposal_title}]({proposal_url})** 的一项异议"
            "需要收集足够的支持票以进入正式讨论阶段。\n\n"
            f"**异议发起人**: <@{result_dto.objector_id}>"
        )

        # 更新或添加字段
        fields_to_update = {
            "当前支持": f"{result_dto.current_supporters} / {result_dto.required_supporters}",
            "所需票数": str(result_dto.required_supporters),
        }
        found_fields = {name: False for name in fields_to_update}

        for i, field in enumerate(new_embed.fields):
            if field.name in fields_to_update:
                new_embed.set_field_at(
                    i, name=field.name, value=fields_to_update[field.name], inline=field.inline
                )
                found_fields[field.name] = True

        for name, value in fields_to_update.items():
            if not found_fields[name]:
                new_embed.add_field(name=name, value=value, inline=True)

        return new_embed

    @staticmethod
    def create_goal_reached_embed(
        original_embed: discord.Embed,
        result_dto: HandleSupportObjectionResultDto,
        guild_id: int,
    ) -> discord.Embed:
        """
        创建一个全新的 "目标达成" 状态的 Embed。
        """
        new_embed = original_embed.copy()

        proposal_url = (
            f"https://discord.com/channels/{guild_id}/{result_dto.proposal_discussion_thread_id}"
        )
        new_description = (
            f"对提案 **[{result_dto.proposal_title}]({proposal_url})** 的异议"
            "已获得足够支持，进入正式讨论阶段\n"
            f"**异议发起人**: <@{result_dto.objector_id}>"
        )

        new_embed.description = new_description

        new_embed.title = "✅ 异议产生票收集完成"
        new_embed.color = discord.Color.green()

        # 更新字段
        fields_to_update = {
            "当前支持": f"{result_dto.current_supporters} / {result_dto.required_supporters}",
            "所需票数": str(result_dto.required_supporters),
        }
        found_fields = {name: False for name in fields_to_update}
        for i, field in enumerate(new_embed.fields):
            if field.name in fields_to_update:
                new_embed.set_field_at(
                    i, name=field.name, value=fields_to_update[field.name], inline=field.inline
                )
                found_fields[field.name] = True

        return new_embed

    @staticmethod
    def update_formal_embed(
        original_embed: discord.Embed, vote_details: VoteDetailDto
    ) -> discord.Embed:
        """
        更新正式异议投票面板上的票数。

        :param original_embed: 原始的Embed对象。
        :param vote_details: 包含最新票数信息的DTO。
        :return: 更新后的Embed对象。
        """
        new_embed = original_embed.copy()

        # 定义字段
        fields_to_update = {
            "✅ 同意异议": f"**{vote_details.approve_votes}**",
            "❌ 反对异议": f"**{vote_details.reject_votes}**",
        }

        # 创建一个列表来跟踪哪些字段已经找到
        found_fields = {name: False for name in fields_to_update}

        # 遍历现有字段进行更新
        for i, field in enumerate(new_embed.fields):
            if field.name in fields_to_update:
                new_embed.set_field_at(
                    i,
                    name=field.name,
                    value=fields_to_update[field.name],
                    inline=True,
                )
                found_fields[field.name] = True

        # 添加尚未找到的字段
        for name, value in fields_to_update.items():
            if not found_fields[name]:
                new_embed.add_field(name=name, value=value, inline=True)

        return new_embed
