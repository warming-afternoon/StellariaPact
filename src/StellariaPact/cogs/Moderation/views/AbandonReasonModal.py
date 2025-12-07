import logging
from typing import TYPE_CHECKING

import discord

from StellariaPact.cogs.Moderation.thread_manager import ProposalThreadManager
from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot

if TYPE_CHECKING:
    from StellariaPact.cogs.Moderation.Cog import Moderation

logger = logging.getLogger(__name__)


class AbandonReasonModal(discord.ui.Modal):
    def __init__(
        self,
        bot: StellariaPactBot,
        thread_manager: ProposalThreadManager,
        cog: "Moderation",
        notify_roles: bool,
    ):
        super().__init__(title="废弃提案原因")
        self.bot = bot
        self.thread_manager = thread_manager
        self.cog = cog
        self.notify_roles = notify_roles
        self.reason = discord.ui.TextInput(
            label="原因",
            style=discord.TextStyle.long,
            placeholder="请详细说明废弃此提案的原因...",
            required=True,
            max_length=4000,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await safeDefer(interaction, ephemeral=True)

        if not isinstance(interaction.channel, discord.Thread):
            return await self.bot.api_scheduler.submit(
                interaction.followup.send("此命令只能在帖子内使用。", ephemeral=True), 1
            )

        await self.cog._initiate_abandon_confirmation(
            interaction, self.reason.value, self.notify_roles
        )
