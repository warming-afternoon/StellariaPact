import logging

import discord

from StellariaPact.cogs.Voting.qo.AdjustVoteTimeQo import AdjustVoteTimeQo
from StellariaPact.cogs.Voting.VotingService import VotingService
from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot

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

    def __init__(self, bot: StellariaPactBot, voting_service: VotingService, thread_id: int):
        super().__init__()
        self.bot = bot
        self.voting_service = voting_service
        self.thread_id = thread_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            hours_to_adjust = int(self.hours.value)
        except ValueError:
            await self.bot.api_scheduler.submit(
                interaction.response.send_message("请输入一个有效的整数。", ephemeral=True),
                priority=1,
            )
            return

        await self.bot.api_scheduler.submit(safeDefer(interaction), priority=1)

        try:
            qo = AdjustVoteTimeQo(
                thread_id=self.thread_id, hours_to_adjust=hours_to_adjust
            )
            async with self.bot.db_handler.get_session() as session:
                session_vo = await self.voting_service.adjust_vote_time(session, qo)

            if session_vo.endTime:
                await self.bot.api_scheduler.submit(
                    interaction.followup.send(
                        f"投票时间已成功调整。新的结束时间为: {discord.utils.format_dt(session_vo.endTime)}",
                        ephemeral=True,
                    ),
                    priority=1,
                )
            else:
                # 这种情况理论上不应该发生，因为 adjust_vote_time 总会设置时间
                await self.bot.api_scheduler.submit(
                    interaction.followup.send(
                        "投票时间已成功调整，但无法获取新的结束时间。", ephemeral=True
                    ),
                    priority=1,
                )
        except Exception as e:
            logger.error(f"调整投票时间时出错: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send(f"操作失败：{e}", ephemeral=True), priority=1
            )


class VoteAdminView(discord.ui.View):
    """
    一个临时的、仅管理员可见的视图，用于管理投票。
    """

    def __init__(self, bot: StellariaPactBot, voting_service: VotingService, thread_id: int):
        super().__init__(timeout=180)
        self.bot = bot
        self.voting_service = voting_service
        self.thread_id = thread_id

    @discord.ui.button(label="调整时间", style=discord.ButtonStyle.secondary)
    async def adjust_time_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        modal = AdjustTimeModal(self.bot, self.voting_service, self.thread_id)
        await interaction.response.send_modal(modal)
