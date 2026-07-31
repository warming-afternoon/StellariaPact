from __future__ import annotations

import discord

from StellariaPact.dto import ObjectionViolationRecordDto


class MaliciousObjectionHistoryModal(discord.ui.Modal):
    """只读展示用户在当前服务器内的恶意违规异议。"""

    def __init__(
        self,
        target_user: discord.User | discord.Member,
        total: int,
        records: list[ObjectionViolationRecordDto],
    ):
        display_name = getattr(target_user, "display_name", target_user.name)
        super().__init__(
            title=f"恶意违规异议 — {display_name}"[:45],
            timeout=300,
        )

        if total == 0:
            summary = f"👤 用户：{target_user.mention}\n📊 当前服务器内暂无恶意违规异议。"
        else:
            summary = (
                f"👤 用户：{target_user.mention}\n"
                f"📊 当前服务器累计：**{total} 条**\n"
                f"以下显示最近 {len(records)} 条"
            )
        self.add_item(discord.ui.TextDisplay(summary))

        for index, record in enumerate(records, start=1):
            self.add_item(discord.ui.TextDisplay(self._format_record(index, record)))

    @staticmethod
    def _format_record(index: int, record: ObjectionViolationRecordDto) -> str:
        objection = discord.utils.escape_markdown(record.choice_text)
        description = discord.utils.escape_markdown(
            record.resolution_description or "未填写"
        )
        created_at = int(record.created_at.timestamp())
        closed_at = int(record.closed_at.timestamp())
        thread_url = (
            f"https://discord.com/channels/{record.guild_id}/{record.thread_id}"
        )
        return (
            f"### {index}. {objection}\n"
            f"**违规描述：** {description}\n"
            f"**提出时间：** <t:{created_at}:F>\n"
            f"**关闭时间：** <t:{closed_at}:F>\n"
            f"[打开所属提案帖]({thread_url})"
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

