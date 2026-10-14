from typing import TYPE_CHECKING

import discord

from ..qo import SubmitQuickPunishmentQo

if TYPE_CHECKING:
    from ..PunishmentCog import PunishmentCog


class OffTopicConfirmationModal(discord.ui.Modal):
    """已有累计处罚时，让管理员选择继续轻罚或转为累计处罚。"""

    def __init__(
        self,
        cog: "PunishmentCog",
        target_user: discord.User | discord.Member,
        message: discord.Message,
        cumulative_count: int,
    ):
        """构建已有累计次数提醒及默认坚持歪楼滑坡的选项。"""
        super().__init__(title="确认快速处罚方式", timeout=300)
        self.cog = cog
        self.target_user = target_user
        self.message = message
        # 次数是打开表单时的快照，提交时由业务层重新计算。
        self.add_item(
            discord.ui.TextDisplay(
                f"该被处罚用户已经进行了 **{cumulative_count} 次累计处罚**，"
                "是否坚持“快速处罚-歪楼滑坡”？选择否将执行累计处罚。"
            )
        )
        # 默认选是，管理员可以主动改为累计处罚。
        self.choice = discord.ui.Select(
            options=[
                discord.SelectOption(label="是", value="yes", default=True),
                discord.SelectOption(label="否", value="no"),
            ],
            min_values=1,
            max_values=1,
            required=True,
        )
        self.add_item(discord.ui.Label(text="是否坚持快速处罚-歪楼滑坡", component=self.choice))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """复用有权限校验的执行入口，并在提交时重算累计次数。"""
        await self.cog.execute_quick_punishment(
            interaction,
            SubmitQuickPunishmentQo(
                message=self.message,
                target_user=self.target_user,
                cumulative=self.choice.values == ["no"],
                off_topic_confirmed=True,
            ),
        )
