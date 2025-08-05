import discord

from ...Moderation.dto.ObjectionDetailsDto import ObjectionDetailsDto


class ObjectionVoteEmbedBuilder:
    """
    一个专门用于构建异议投票相关 Embed 的类。
    """

    @staticmethod
    def create_embed(objection_dto: ObjectionDetailsDto) -> discord.Embed:
        """
        创建异议投票的初始 Embed。

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
            value=f"> {objection_dto.objection_reason}",
            inline=False,
        )
        embed.add_field(
            name="投票规则",
            value="请讨论者进行投票。\n如果“赞成异议”票数超过“反对异议”票数，"
            "则原提案将被冻结，此异议将进入后续处理流程",
            inline=False,
        )

        return embed
