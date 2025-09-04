import asyncio
import logging

import discord

from ....share.SafeDefer import safeDefer
from ....share.StellariaPactBot import StellariaPactBot
from ..VotingLogic import VotingLogic

logger = logging.getLogger(__name__)


class AdjustTimeModal(discord.ui.Modal, title="调整投票时间"):
    """
    一个让管理员输入要调整的小时数的模态框。
    """

    hours = discord.ui.TextInput(
        label="调整的小时数",
        placeholder="输入一个整数，例如 24 (延长一天) 或 -12 (缩短半天)",
        required=True,
    )

    def __init__(self, bot: StellariaPactBot, thread_id: int, logic: VotingLogic):
        super().__init__(timeout=1800)
        self.bot = bot
        self.thread_id = thread_id
        self.logic = logic

    async def on_submit(self, interaction: discord.Interaction):
        await safeDefer(interaction, ephemeral=True)

        try:
            hours_to_adjust = int(self.hours.value)
        except ValueError:
            await self.bot.api_scheduler.submit(
                interaction.followup.send("请输入一个有效的整数。", ephemeral=True),
                priority=1,
            )
            return

        try:
            await self.logic.adjust_vote_time(
                thread_id=self.thread_id,
                hours_to_adjust=hours_to_adjust,
                operator=interaction.user,
            )

        except Exception as e:
            logger.error(f"调整投票时间时出错: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send(f"操作失败：{e}", ephemeral=True), priority=1
            )
