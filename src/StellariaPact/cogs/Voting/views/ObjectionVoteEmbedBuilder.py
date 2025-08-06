import discord

from ...Moderation.dto.HandleSupportObjectionResultDto import (
    HandleSupportObjectionResultDto,
)
from ...Moderation.dto.ObjectionDetailsDto import ObjectionDetailsDto
from ..dto.VoteDetailDto import VoteDetailDto


class ObjectionVoteEmbedBuilder:
    """
    一个专门用于构建异议投票相关 Embed 的类。
    """

    @staticmethod
    def create_formal_embed(objection_dto: ObjectionDetailsDto) -> discord.Embed:
        """
        创建正式异议投票的初始 Embed。

        :param objection_dto: 包含异议和提案信息的DTO。
        :return: 一个 discord.Embed 对象。
        """
        embed = discord.Embed(
            title="裁决投票：是否同意此异议？",
            description=f"此投票用于裁决由 <@{objection_dto.objector_id}> 发起的，"
            f"针对提案 **「{objection_dto.proposal_title}」** 的异议。",
            color=discord.Color.orange(),
        )

        embed.add_field(
            name="异议理由",
            value=f"{objection_dto.objection_reason}",
            inline=False,
        )
        embed.add_field(
            name="投票规则",
            value="请讨论者进行投票。\n如果“赞成异议”票数超过“反对异议”票数，"
            "则原提案将被冻结，此异议将进入后续处理流程",
            inline=False,
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

        # 1. 重构描述以保留链接
        proposal_url = (
            f"https://discord.com/channels/{guild_id}/{result_dto.proposal_discussion_thread_id}"
        )
        new_embed.description = (
            f"对提案 **[{result_dto.proposal_title}]({proposal_url})** 的一项异议"
            "需要收集足够的支持票以进入正式讨论阶段。\n\n"
            f"**异议发起人**: <@{result_dto.objector_id}>"
        )

        # 2. 更新或添加字段
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
