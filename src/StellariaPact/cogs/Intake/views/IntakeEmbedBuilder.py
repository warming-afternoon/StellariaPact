from __future__ import annotations

import logging
from typing import Optional

import discord

from StellariaPact.models.ProposalIntake import ProposalIntake
from StellariaPact.share.enums import IntakeStatus

logger = logging.getLogger(__name__)


class IntakeEmbedBuilder:
    """
    专门负责构建预审（Intake）相关的 Embed UI
    """

    @staticmethod
    def _get_jump_url(guild_id: int, channel_id: int, message_id: Optional[int] = None) -> str:
        """构建 Discord 跳转链接"""
        if message_id:
            return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
        return f"https://discord.com/channels/{guild_id}/{channel_id}"

    @staticmethod
    def _get_review_color(status: int) -> discord.Color:
        """根据状态获取对应的颜色"""
        status_map = {
            IntakeStatus.PENDING_REVIEW: discord.Color.yellow(),
            IntakeStatus.SUPPORT_COLLECTING: discord.Color.green(),
            IntakeStatus.APPROVED: discord.Color.dark_green(),
            IntakeStatus.REJECTED: discord.Color.red(),
            IntakeStatus.MODIFICATION_REQUIRED: discord.Color.orange(),
        }
        return status_map.get(IntakeStatus(status), discord.Color.default())

    @staticmethod
    def _get_review_status_text(status: int) -> str:
        """根据状态获取对应的状态文本"""
        status_map = {
            IntakeStatus.PENDING_REVIEW: "🔵 待审核",
            IntakeStatus.SUPPORT_COLLECTING: "🟢 审核通过",
            IntakeStatus.APPROVED: "✅ 已立案",
            IntakeStatus.REJECTED: "🔴 已拒绝",
            IntakeStatus.MODIFICATION_REQUIRED: "🟡 需要修改",
        }
        return status_map.get(IntakeStatus(status), "未知状态")

    @staticmethod
    def build_review_embed(intake: ProposalIntake) -> discord.Embed:
        """构建审核贴的 Embed"""
        status_text = IntakeEmbedBuilder._get_review_status_text(intake.status)
        color = IntakeEmbedBuilder._get_review_color(intake.status)

        embed = discord.Embed(
            title=f"📝 提案预审核: {intake.title}",
            description=f"**提交人**: <@{intake.author_id}>",
            color=color,
        )

        # 如果已经开启了支持票收集，添加跳转到投票消息的链接
        if intake.status >= IntakeStatus.SUPPORT_COLLECTING and intake.voting_message_id:
            # 这里的投票频道 ID 通常需要从配置拿，为了方便，我们可以在 Embed 中展示
            # 注意：这里需要投票频道的 channel_id，但当前模型中没有存储
            # 我们可以先不添加这个链接，或者从配置中获取
            pass

        embed.add_field(name="草案ID", value=f"`{intake.id}`", inline=True)
        embed.add_field(name="状态", value=status_text, inline=True)
        embed.add_field(name="原因", value=intake.reason, inline=False)
        embed.add_field(name="动议", value=intake.motion, inline=False)
        embed.add_field(name="方案", value=intake.implementation, inline=False)
        embed.add_field(name="执行人", value=intake.executor, inline=False)
        embed.set_footer(text="最后更新于")
        embed.timestamp = discord.utils.utcnow()
        return embed

    @staticmethod
    def build_support_embed(intake: ProposalIntake) -> discord.Embed:
        """构建用于收集支持票的嵌入消息。"""
        embed = discord.Embed(
            title=f"📣 草案寻求支持: {intake.title}",
            description=(
                f"该草案已通过管理组初步审核，现进入社区支持票收集阶段。\n"
                f"达到 **{intake.required_votes}** 票支持后，将自动转为正式提案进入讨论。"
            ),
            color=discord.Color.blue(),
        )
        embed.add_field(name="草案ID", value=f"`{intake.id}`", inline=True)
        embed.add_field(name="发起人", value=f"<@{intake.author_id}>", inline=True)
        embed.add_field(name="动议摘要", value=intake.motion, inline=False)
        embed.set_footer(text="如果你支持该草案成为正式提案，请点击下方按钮。")
        return embed

    @staticmethod
    def build_support_result_embed(
        intake: ProposalIntake, success: bool, thread_id: Optional[int] = None
    ) -> discord.Embed:
        """
        构建支持票收集结束后的结果 Embed

        Args:
            intake: 草案对象
            success: 是否成功达到支持票数
            thread_id: 成功时关联的讨论帖ID（可选）
        """
        if success:
            embed = discord.Embed(
                title=f"✅ [已立案] {intake.title}",
                description=f"该草案已获得足够的社区支持（{intake.required_votes} 票），已正式立案。",
                color=discord.Color.green(),
            )
            embed.add_field(name="草案ID", value=f"`{intake.id}`", inline=True)
            embed.add_field(name="发起人", value=f"<@{intake.author_id}>", inline=True)
            if thread_id and intake.guild_id:
                # 构建跳转到新讨论帖的链接
                url = IntakeEmbedBuilder._get_jump_url(intake.guild_id, thread_id)
                embed.add_field(name="正式讨论帖", value=f"👉 [点击前往讨论]({url})", inline=False)
            embed.set_footer(text="草案支持票收集已成功完成")
        else:
            embed = discord.Embed(
                title=f"❌ [收集失败] {intake.title}",
                description="当前草案未能在截止日期前获得足够支持，未能进入讨论阶段。",
                color=discord.Color.light_gray(),
            )
            embed.add_field(name="草案ID", value=f"`{intake.id}`", inline=True)
            embed.add_field(name="发起人", value=f"<@{intake.author_id}>", inline=True)
            # 即使失败，也可以提供一个跳转回原审核贴（讨论过程）的链接
            if intake.review_thread_id and intake.guild_id:
                url = IntakeEmbedBuilder._get_jump_url(intake.guild_id, intake.review_thread_id)
                embed.add_field(
                    name="过程回顾", value=f"[点击查看审核贴详情]({url})", inline=False
                )
            embed.set_footer(text="草案支持票收集已结束（未达标）")

        embed.timestamp = discord.utils.utcnow()
        return embed
