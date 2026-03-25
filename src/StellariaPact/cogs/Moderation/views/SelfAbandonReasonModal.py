import logging
from typing import TYPE_CHECKING

import discord

from StellariaPact.cogs.Moderation.thread_manager import ProposalThreadManager
from StellariaPact.share import StellariaPactBot

if TYPE_CHECKING:
    from StellariaPact.cogs.Moderation.Cog import Moderation

logger = logging.getLogger(__name__)


class SelfAbandonReasonModal(discord.ui.Modal):
    def __init__(
        self,
        bot: StellariaPactBot,
        thread_manager: ProposalThreadManager,
        cog: "Moderation",
    ):
        super().__init__(title="废弃提案原因")
        self.bot = bot
        self.thread_manager = thread_manager
        self.cog = cog

        self.reason = discord.ui.TextInput(
            label="原因",
            style=discord.TextStyle.long,
            placeholder="请详细说明废弃此提案的原因...",
            required=True,
            max_length=4000,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        # 移交回 Cog 进行具体处理
        await self.cog._handle_self_abandon(interaction, self.reason.value)
