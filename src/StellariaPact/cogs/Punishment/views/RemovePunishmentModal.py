from typing import TYPE_CHECKING

import discord

from ..dto import ThreadPunishmentHistoryDto
from ..qo import SubmitPunishmentRemovalQo
from .PunishmentHistoryModal import PunishmentHistoryModal

if TYPE_CHECKING:
    from ..PunishmentCog import PunishmentCog


class RemovePunishmentModal(discord.ui.Modal):
    """展示处罚快照，并将解除表单交给控制器处理。"""

    def __init__(
        self,
        cog: "PunishmentCog",
        target_user: discord.User | discord.Member,
        *,
        thread: discord.Thread,
        history: ThreadPunishmentHistoryDto,
    ):
        """绑定最新处罚记录并构建摘要、理由和简化详情。"""
        super().__init__(title="解除提案处罚理由", timeout=1000)
        self.cog = cog
        self.target_user = target_user
        self.thread = thread
        if history.latest is None:
            raise ValueError("解除表单缺少最新处罚记录。")
        self.expected_record_id = history.latest.id

        # 摘要使用独立 DTO，不持有数据库会话或 ORM 实体。
        self.add_item(
            discord.ui.TextDisplay(PunishmentHistoryModal.format_summary(target_user, history))
        )
        self.reason = discord.ui.TextInput(
            label="解除理由",
            style=discord.TextStyle.long,
            placeholder="请输入解除该用户此处罚的原因...",
            required=True,
            max_length=1000,
        )
        self.add_item(self.reason)

        # 最近记录统一复用历史视图的简化展示格式。
        details = "\n\n".join(
            PunishmentHistoryModal.format_record(index, record)
            for index, record in enumerate(history.records, start=1)
        )
        self.add_item(discord.ui.TextDisplay(details or "暂无处罚详情。"))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """提交解除理由及绑定的记录，由控制器重新校验和执行。"""
        # 表单只收集输入，权限、处罚状态及公示由控制器协调。
        await self.cog.submit_remove_punishment(
            interaction,
            SubmitPunishmentRemovalQo(
                thread=self.thread,
                target_user=self.target_user,
                expected_record_id=self.expected_record_id,
                reason=self.reason.value,
            ),
        )
