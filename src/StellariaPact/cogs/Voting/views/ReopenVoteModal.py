import logging

import discord

from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


class ReopenVoteModal(discord.ui.Modal, title="重新开启投票"):
    """
    一个让管理员输入投票重新开启时长的模态框。
    """

    duration_hours = discord.ui.TextInput(
        label="新的投票持续小时数",
        placeholder="输入一个正整数，例如 24 (代表从现在起再持续24小时)",
        required=True,
    )

    def __init__(self, bot: StellariaPactBot, thread_id: int, message_id: int):
        super().__init__(timeout=1800)
        self.bot = bot
        self.thread_id = thread_id
        self.message_id = message_id

    async def on_submit(self, interaction: discord.Interaction):
        await safeDefer(interaction, ephemeral=True)

        try:
            hours_to_add = int(self.duration_hours.value)
            if hours_to_add <= 0:
                raise ValueError("小时数必须为正整数。")
        except ValueError as e:
            await self.bot.api_scheduler.submit(
                interaction.followup.send(f"输入无效: {e}", ephemeral=True),
                priority=1,
            )
            return

        self.bot.dispatch(
            "vote_reopened",
            interaction=interaction,
            thread_id=self.thread_id,
            message_id=self.message_id,
            hours_to_add=hours_to_add,
        )
