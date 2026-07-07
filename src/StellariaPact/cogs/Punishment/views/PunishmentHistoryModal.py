from __future__ import annotations

import discord

from StellariaPact.models.PunishmentRecord import PunishmentRecord


class PunishmentHistoryModal(discord.ui.Modal):
    """只读展示用户在当前帖子中的处罚历史。"""

    def __init__(
        self,
        target_user: discord.User | discord.Member,
        total: int,
        records: list[PunishmentRecord],
    ):
        """构造模态框，生成摘要信息与逐条处罚记录的只读展示项。"""
        # 优先使用服务器昵称作为标题前缀
        display_name = getattr(target_user, "display_name", target_user.name)
        super().__init__(title=f"本帖处罚记录 — {display_name}"[:45], timeout=300)

        # 根据是否有处罚记录生成不同的摘要文本
        if total == 0:
            summary = f"👤 用户：{target_user.mention}\n📊 该用户在本帖暂无处罚记录。"
        else:
            summary = (
                f"👤 用户：{target_user.mention}\n"
                f"📊 本帖累计处罚：**{total} 次**\n"
                f"以下显示最近 {len(records)} 条"
            )
        self.add_item(discord.ui.TextDisplay(summary))

        # 逐条渲染处罚记录为只读文本展示
        for index, record in enumerate(records, start=1):
            self.add_item(discord.ui.TextDisplay(self._format_record(index, record)))

    @staticmethod
    def _format_record(index: int, record: PunishmentRecord) -> str:
        """将单条处罚记录格式化为带序号、时间戳与处理结果的 Markdown 文本。"""
        # 将创建时间转换为 Unix 时间戳供 Discord 时间戳渲染
        created_timestamp = int(record.created_at.timestamp())
        # 投票权与禁言状态的可读描述
        voting = "保留投票资格" if record.voting_allowed else "剥夺投票资格"
        if record.mute_end_time is None:
            mute = "未禁言"
        else:
            mute_timestamp = int(record.mute_end_time.timestamp())
            mute = f"禁言至 <t:{mute_timestamp}:F>"

        # 转义原因中的 Markdown 字符，防止格式注入
        reason = discord.utils.escape_markdown(record.reason)
        # 生成违规消息链接或提示不可用
        message_link = (
            f"[查看违规消息]({record.source_message_url})"
            if record.source_message_url
            else "违规消息链接不可用"
        )
        return (
            f"### {index}. <t:{created_timestamp}:F>\n"
            f"**原因：** {reason}\n"
            f"**处理：** {voting}；{mute}\n"
            f"{message_link}"
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """模态框提交时静默确认，仅关闭弹窗不执行额外操作。"""
        await interaction.response.defer(ephemeral=True)
