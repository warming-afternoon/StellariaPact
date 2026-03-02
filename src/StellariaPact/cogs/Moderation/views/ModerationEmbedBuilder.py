from datetime import datetime, timezone
from typing import Dict

import discord

from StellariaPact.cogs.Moderation.qo import BuildConfirmationEmbedQo
from StellariaPact.share.enums import ConfirmationStatus


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
        title_map = {
            "proposal_execution": {
                ConfirmationStatus.PENDING.value: "⏳ 流程确认中：进入执行阶段",
                ConfirmationStatus.COMPLETED.value: "✅ 确认完成：提案已进入执行阶段",
                ConfirmationStatus.CANCELED.value: "❌ 操作已取消",
            },
            "proposal_completion": {
                ConfirmationStatus.PENDING.value: "⏳ 流程确认中：确定提案完成",
                ConfirmationStatus.COMPLETED.value: "✅ 确认完成：提案已进入完成阶段",
                ConfirmationStatus.CANCELED.value: "❌ 操作已取消",
            },
            "proposal_abandonment": {
                ConfirmationStatus.PENDING.value: "⏳ 流程确认中：废弃提案",
                ConfirmationStatus.COMPLETED.value: "✅ 确认完成：提案已废弃",
                ConfirmationStatus.CANCELED.value: "❌ 操作已取消",
            },
            "proposal_rediscuss": {
                ConfirmationStatus.PENDING.value: "⏳ 流程确认中：恢复为讨论中",
                ConfirmationStatus.COMPLETED.value: "✅ 确认完成：提案已恢复为讨论中",
                ConfirmationStatus.CANCELED.value: "❌ 操作已取消",
            },
        }
        color_map = {
            ConfirmationStatus.PENDING.value: discord.Color.yellow(),
            ConfirmationStatus.COMPLETED.value: discord.Color.green(),
            ConfirmationStatus.CANCELED.value: discord.Color.red(),
        }

        # 获取默认标题和颜色，以防 context 未知
        default_titles = title_map.get("proposal_execution", {})
        title = default_titles.get(qo.status, "操作状态未知")
        color = color_map.get(qo.status, discord.Color.default())

        # 根据 context 获取特定的标题
        if qo.context in title_map:
            title = title_map[qo.context].get(qo.status, title)

        embed = discord.Embed(title=title, color=color)

        if qo.status == ConfirmationStatus.CANCELED.value and qo.canceler_id:
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

        # 如果存在原因，则显示
        if qo.reason:
            embed.add_field(name="原因", value=qo.reason, inline=False)

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

