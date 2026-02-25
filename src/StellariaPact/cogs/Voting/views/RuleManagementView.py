import discord

from StellariaPact.cogs.Voting.views.AdjustTimeModal import AdjustTimeModal
from StellariaPact.share import StellariaPactBot, safeDefer


class RuleManagementView(discord.ui.View):
    """规则管理面板：用于管理投票规则。"""

    def __init__(self, bot: StellariaPactBot, thread_id: int, message_id: int):
        super().__init__(timeout=900)
        self.bot = bot
        self.thread_id = thread_id
        self.message_id = message_id

    @discord.ui.button(label="匿名投票", style=discord.ButtonStyle.primary, row=0)
    async def toggle_anonymous(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safeDefer(interaction, ephemeral=True)
        self.bot.dispatch(
            "vote_anonymous_toggled",
            interaction=interaction,
            message_id=self.message_id,
            thread_id=self.thread_id,
        )

    @discord.ui.button(label="实时票数", style=discord.ButtonStyle.primary, row=0)
    async def toggle_realtime(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safeDefer(interaction, ephemeral=True)
        self.bot.dispatch(
            "vote_realtime_toggled",
            interaction=interaction,
            message_id=self.message_id,
            thread_id=self.thread_id,
        )

    @discord.ui.button(label="结束通知", style=discord.ButtonStyle.primary, row=0)
    async def toggle_notify(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safeDefer(interaction, ephemeral=True)
        self.bot.dispatch(
            "vote_notify_toggled",
            interaction=interaction,
            message_id=self.message_id,
            thread_id=self.thread_id,
        )

    @discord.ui.button(label="调整时间", style=discord.ButtonStyle.secondary, row=1)
    async def adjust_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AdjustTimeModal(self.bot, self.thread_id, self.message_id)
        await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), priority=1)
