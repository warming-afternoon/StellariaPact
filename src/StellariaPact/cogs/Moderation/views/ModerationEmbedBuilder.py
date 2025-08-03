from datetime import datetime, timezone
from typing import Dict

import discord
from zoneinfo import ZoneInfo

from ..qo.BuildConfirmationEmbedQo import BuildConfirmationEmbedQo


class ModerationEmbedBuilder:
    """
    构建议事管理相关操作的 Embed 消息。
    """

    @staticmethod
    def build_confirmation_embed(
        qo: "BuildConfirmationEmbedQo", bot_user: discord.ClientUser
    ) -> discord.Embed:
        """
        根据确认会话状态构建Embed。
        """
        title = "⏳ 流程确认中：进入执行阶段"
        color = discord.Color.yellow()

        if qo.status == 1:  # 已完成
            title = "✅ 确认完成：提案已进入执行阶段"
            color = discord.Color.green()
        elif qo.status == 2:  # 已取消
            title = "❌ 操作已取消"
            color = discord.Color.red()

        embed = discord.Embed(title=title, color=color)

        if qo.status == 2 and qo.canceler_id:
            embed.description = f"操作由 <@{qo.canceler_id}> 取消。"

        confirmed_lines = []
        pending_lines = []

        # 获取角色名称和确认者ID
        confirmed_parties: Dict[str, int] = qo.confirmed_parties

        for role_key in qo.required_roles:
            role_name = qo.role_display_names.get(role_key, role_key)
            user_id = confirmed_parties.get(role_key)
            if user_id:
                confirmed_lines.append(f"✅ **{role_name}**: <@{user_id}>")
            else:
                pending_lines.append(f"⏳ **{role_name}**: 待确认")

        confirmed_field_value = "\n".join(confirmed_lines) if confirmed_lines else "无"
        embed.add_field(name="已确认方", value=confirmed_field_value, inline=False)

        if pending_lines:
            pending_field_value = "\n".join(pending_lines)
            embed.add_field(name="待确认方", value=pending_field_value, inline=False)
        return embed

    @staticmethod
    def build_status_change_embed(
        thread_name: str,
        new_status: str,
        moderator: discord.User | discord.Member,
        reason: str | None = None,
    ) -> discord.Embed:
        """
        构建状态变更通知的Embed。
        """
        embed = discord.Embed(
            title=f"📢 提案状态变更: {thread_name}",
            description=f"提案的状态已被 {moderator.mention} 变更为{new_status}",
            color=discord.Color.orange(),
        )
        if reason:
            embed.add_field(name="原因", value=reason, inline=False)
        embed.timestamp = datetime.now(timezone.utc)
        return embed

    @staticmethod
    def create_kick_embed(
        moderator: discord.Member,
        kicked_user: discord.User | discord.Member,
        reason: str,
        target_message: discord.Message,
    ) -> discord.Embed:
        """
        创建踢出提案的处罚公示 Embed。
        """
        embed = discord.Embed(
            title="议事成员资格变动公示",
            description=f"**目标用户**: {kicked_user.mention}\n**处理方式**: 剥夺本帖议事资格",
            color=discord.Color.red(),
            timestamp=datetime.now(ZoneInfo("UTC")),
        )
        embed.add_field(name="处理理由", value=reason, inline=False)
        embed.add_field(
            name="相关消息", value=f"[点击跳转]({target_message.jump_url})", inline=True
        )
        embed.add_field(name="操作人员", value=moderator.mention, inline=True)
        return embed
