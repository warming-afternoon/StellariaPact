from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import discord

from StellariaPact.dto.ProposalIntakeDto import ProposalIntakeDto
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

        submitted_at = datetime.now(timezone.utc)
        submitted_timestamp = int(submitted_at.timestamp())

        status_text = IntakeEmbedBuilder._get_review_status_text(intake.status)
        if " " in status_text:
            emoji, status_desc = status_text.split(" ", 1)
        else:
            emoji = ""
            status_desc = status_text

        content = (
            f"👤 **提案人：** <@{intake.author_id}>\n"
            f"📅 **提交时间：** <t:{submitted_timestamp}:f>\n"
            f"🆔 **草案ID：** `{intake.id}`\n\n"
            "---\n\n"
            f"🏷️ **议案标题**\n{intake.title}\n\n"
            f"📝 **提案原因**\n{intake.reason}\n\n"
            f"📋 **议案动议**\n{intake.motion}\n\n"
            f"🔧 **执行方案**\n{intake.implementation}\n\n"
            f"👨‍💼 **议案执行人**\n{intake.executor}\n\n"
            "---\n\n"
            f"{emoji} **状态：** {status_desc}\n"
        )
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
        intake: ProposalIntakeDto,
        success: bool,
        thread_id: Optional[int] = None,
        current_votes: int = 0,
    ) -> discord.Embed:
        """
        构建支持票收集结束后的结果 Embed

        Args:
            intake: 草案DTO对象
            success: 是否成功达到支持票数
            thread_id: 成功时关联的讨论帖ID（可选）
            current_votes: 当前获得的票数
        """
        if success:
            # 构建跳转URL
            thread_jump_url = None
            if thread_id and intake.guild_id:
                thread_jump_url = IntakeEmbedBuilder._get_jump_url(intake.guild_id, thread_id)

            # 创建embed，如果有thread_jump_url则设置url参数
            embed_kwargs = {
                "title": f"{intake.title}",
                "description": "该提案已收集到足够的支持票，进入正式讨论阶段。",
                "color": discord.Color.green(),
            }
            if thread_jump_url:
                embed_kwargs["url"] = thread_jump_url

            embed = discord.Embed(**embed_kwargs)
            embed.add_field(name="发起人", value=f"<@{intake.author_id}>", inline=True)
            embed.add_field(
                name="票数", value=f"**{current_votes}** / {intake.required_votes}", inline=True
            )
            embed.add_field(name="状态", value="✅ 已立案", inline=True)
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
