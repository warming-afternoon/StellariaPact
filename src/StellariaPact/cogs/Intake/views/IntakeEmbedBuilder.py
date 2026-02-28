from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import discord

from StellariaPact.dto.ProposalIntakeDto import ProposalIntakeDto
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
    def build_review_embed(intake: ProposalIntakeDto) -> discord.Embed:
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
    def build_review_content(intake: ProposalIntakeDto) -> str:
        """构建审核贴的纯文本内容"""

        submitted_at = datetime.utcnow()
        submitted_timestamp = int(submitted_at.timestamp())

        status_text = IntakeEmbedBuilder._get_review_status_text(intake.status)
        if " " in status_text:
            emoji, status_desc = status_text.split(" ", 1)
        else:
            emoji = ""
            status_desc = status_text

        content = f"""👤 **提案人：** <@{intake.author_id}>\n📅 **提交时间：** <t:{submitted_timestamp}:f>\n🆔 **草案ID：** `{intake.id}`\n\n---\n\n🏷️ **议案标题**\n{intake.title}\n\n📝 **提案原因**\n{intake.reason}\n\n📋 **议案动议**\n{intake.motion}\n\n🔧 **执行方案**\n{intake.implementation}\n\n👨‍💼 **议案执行人**\n{intake.executor}\n\n---\n\n{emoji} **状态：** {status_desc}\n"""
        return content.strip()

    @staticmethod
    def build_support_embed(intake: ProposalIntakeDto, current_votes: int = 0) -> discord.Embed:
        """构建用于收集支持票的嵌入消息"""
        embed = discord.Embed(
            title=f"{intake.title}",
            description=(
                "该提案已通过管理组初步审核，现进入社区支持票收集阶段。\n"
                f"达到 **{intake.required_votes}** 票支持后，将自动转为正式提案进入讨论。"
            ),
            color=discord.Color.blue(),
        )
        embed.add_field(name="发起人", value=f"<@{intake.author_id}>", inline=True)
        embed.add_field(
            name="票数", value=f"**{current_votes}** / {intake.required_votes}", inline=True
        )
        embed.add_field(name="状态", value="🟢 支持票收集中", inline=True)
        embed.add_field(name="议案标题", value=intake.title, inline=False)
        embed.add_field(name="提案原因", value=intake.reason, inline=False)
        embed.add_field(name="议案动议", value=intake.motion, inline=False)
        embed.add_field(name="执行方案", value=intake.implementation, inline=False)
        embed.add_field(name="议案执行人", value=intake.executor, inline=False)
        embed.set_footer(text="点击下方按钮以支持, 再次点击可撤回支持。")
        return embed

    @staticmethod
    def build_support_result_embed(
        intake: ProposalIntake,
        success: bool,
        thread_id: Optional[int] = None,
        current_votes: int = 0,
    ) -> discord.Embed:
        """
        构建支持票收集结束后的结果 Embed

        Args:
            intake: 草案对象
            success: 是否成功达到支持票数
            thread_id: 成功时关联的讨论帖ID（可选）
            current_votes: 当前获得的票数
        """
        if success:
            embed = discord.Embed(
                title=f"✅ [已通过] {intake.title}",
                description="",
                color=discord.Color.green(),
            )
            embed.add_field(name="发起人", value=f"<@{intake.author_id}>", inline=True)
            embed.add_field(
                name="票数", value=f"**{current_votes}** / {intake.required_votes}", inline=True
            )
            embed.add_field(name="状态", value="✅ 已立案", inline=True)
            if thread_id and intake.guild_id:
                # 构建跳转到新讨论帖的链接
                url = IntakeEmbedBuilder._get_jump_url(intake.guild_id, thread_id)
                embed.add_field(name="正式讨论帖", value=f"👉 [点击前往讨论]({url})", inline=False)
        else:
            embed = discord.Embed(
                title=f"❌ [收集失败] {intake.title}",
                description="当前草案未能在截止日期前获得足够支持，未能进入讨论阶段。",
                color=discord.Color.light_gray(),
            )
            embed.add_field(name="发起人", value=f"<@{intake.author_id}>", inline=True)
            embed.add_field(
                name="票数", value=f"**{current_votes}** / {intake.required_votes}", inline=True
            )
            embed.add_field(name="状态", value="❌ 收集失败", inline=True)

        # 添加提案详细信息
        embed.add_field(name="议案标题", value=intake.title, inline=False)
        embed.add_field(name="提案原因", value=intake.reason, inline=False)
        embed.add_field(name="议案动议", value=intake.motion, inline=False)
        embed.add_field(name="执行方案", value=intake.implementation, inline=False)
        embed.add_field(name="议案执行人", value=intake.executor, inline=False)

        embed.timestamp = discord.utils.utcnow()
        return embed
