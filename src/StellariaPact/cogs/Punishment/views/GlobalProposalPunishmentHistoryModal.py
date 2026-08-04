from __future__ import annotations

from datetime import datetime, timezone

import discord

from StellariaPact.models.GlobalProposalPunishment import GlobalProposalPunishment
from StellariaPact.share.enums import PunishmentType


class GlobalProposalPunishmentHistoryModal(discord.ui.Modal):
    """只读展示用户在机器人全局范围内的提案处罚历史。"""

    _TYPE_LABELS = {
        PunishmentType.PERMANENT_VOTING.value: "永久投票资格限制",
        PunishmentType.PROPOSAL_VIOLATION.value: "限时提案违规处罚",
    }

    def __init__(
        self,
        target_user: discord.User | discord.Member,
        total: int,
        records: list[GlobalProposalPunishment],
        *,
        now: datetime | None = None,
    ) -> None:
        """构造最多包含四条详情的全局处罚历史弹窗。"""
        display_name = getattr(target_user, "display_name", target_user.name)
        super().__init__(title=f"全局提案处罚 — {display_name}"[:45], timeout=300)
        current_time = now or datetime.now(timezone.utc)

        if total == 0:
            summary = f"👤 用户：{target_user.mention}\n暂无全局提案处罚记录"
        else:
            summary = (
                f"👤 用户：{target_user.mention}\n"
                f"📊 累计处罚：**{total} 次**\n"
                f"以下显示最近 {len(records)} 条"
            )
        self.add_item(discord.ui.TextDisplay(summary))

        # Discord Modal 最多容纳五个顶层组件：一条摘要和最近四条记录。
        for index, record in enumerate(records[:4], start=1):
            self.add_item(
                discord.ui.TextDisplay(self._format_record(index, record, current_time))
            )

    @classmethod
    def _format_record(
        cls,
        index: int,
        record: GlobalProposalPunishment,
        now: datetime,
    ) -> str:
        """将处罚类型、实时状态和来源信息格式化为只读 Markdown。"""
        type_label = cls._TYPE_LABELS.get(record.punishment_type, record.punishment_type)
        status = cls._get_status(record, now)
        reason = discord.utils.escape_markdown(record.reason)
        created_at = cls._format_time(record.created_at)
        expires_at = (
            cls._format_time(record.expires_at) if record.expires_at else "永久有效"
        )
        source_link = (
            f"[查看来源频道](https://discord.com/channels/"
            f"{record.origin_guild_id}/{record.origin_channel_id})"
        )
        evidence_link = (
            f" · [查看处罚依据]({record.evidence_url})" if record.evidence_url else ""
        )

        lines = [
            f"### {index}. {type_label} · {status}",
            f"**处罚理由：** {reason}",
            f"**执行人：** <@{record.moderator_id}>",
            f"**生效时间：** {created_at}",
            f"**截止时间：** {expires_at}",
        ]
        if record.lifted_at:
            lift_reason = discord.utils.escape_markdown(record.lift_reason or "未填写")
            lifted_by = (
                f"<@{record.lifted_by_id}>" if record.lifted_by_id is not None else "未知"
            )
            lines.append(
                f"**解除/覆盖：** {lifted_by} 于 {cls._format_time(record.lifted_at)}"
                f"（{lift_reason}）"
            )
        lines.append(f"{source_link}{evidence_link}")
        return "\n".join(lines)

    @staticmethod
    def _get_status(record: GlobalProposalPunishment, now: datetime) -> str:
        """根据解除、覆盖和到期字段实时计算处罚状态。"""
        if record.lifted_at is not None:
            return "已覆盖" if "覆盖" in (record.lift_reason or "") else "已解除"
        if record.expires_at is not None and record.expires_at <= now:
            return "已到期"
        return "生效中"

    @staticmethod
    def _format_time(value: datetime) -> str:
        """将时间转换为 Discord 可按用户时区渲染的时间戳。"""
        return f"<t:{int(value.timestamp())}:F>"

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """关闭只读弹窗时不执行任何业务操作。"""
        await interaction.response.defer(ephemeral=True)
