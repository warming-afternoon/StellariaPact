import logging
from typing import TYPE_CHECKING, cast

import discord

from ....share.SafeDefer import safeDefer
from ..Cog import Voting
from ..qo.RecordVoteQo import RecordVoteQo

if TYPE_CHECKING:
    from ....share.StellariaPactBot import StellariaPactBot


logger = logging.getLogger(__name__)


class ObjectionVoteView(discord.ui.View):
    """
    专门用于异议投票的视图。
    提供“赞成推翻”和“反对推翻”的按钮。
    """

    def __init__(self, bot: "StellariaPactBot", *, timeout: float | None = None):
        super().__init__(timeout=timeout)
        self.bot = bot

    async def _handle_vote(self, interaction: discord.Interaction, choice: int):
        """
        处理投票的核心逻辑。
        """
        await self.bot.api_scheduler.submit(safeDefer(interaction), priority=1)

        if not isinstance(interaction.channel, discord.Thread):
            logger.warning(f"投票交互发生在一个非帖子频道 ({interaction.channel_id}) 中。")
            await self.bot.api_scheduler.submit(
                interaction.followup.send("投票只能在帖子中进行。", ephemeral=True), priority=1
            )
            return

        try:
            voting_cog = cast(Voting, self.bot.get_cog("Voting"))
            if not voting_cog:
                await interaction.followup.send(
                    "投票系统组件未就绪，请联系管理员。", ephemeral=True
                )
                return

            if not interaction.message:
                await interaction.followup.send("无法找到原始投票消息。", ephemeral=True)
                return

            await voting_cog.logic.record_vote_and_get_details(
                RecordVoteQo(
                    user_id=interaction.user.id,
                    message_id=interaction.message.id,
                    choice=choice,
                )
            )
            await self.bot.api_scheduler.submit(
                interaction.followup.send("您的投票已记录！", ephemeral=True), priority=1
            )
        except ValueError as e:
            logger.warning(f"记录投票失败: {e}")
            await self.bot.api_scheduler.submit(
                interaction.followup.send(str(e), ephemeral=True), priority=1
            )
        except Exception as e:
            logger.error(f"处理投票时发生未知错误: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send("处理您的投票时发生未知错误。", ephemeral=True),
                priority=1,
            )

    @discord.ui.button(
        label="赞成异议", style=discord.ButtonStyle.danger, custom_id="objection_vote_for"
    )
    async def for_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        处理“赞成异议”按钮的点击事件。
        """
        await self._handle_vote(interaction, 1)

    @discord.ui.button(
        label="反对异议", style=discord.ButtonStyle.secondary, custom_id="objection_vote_against"
    )
    async def against_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        处理“反对异议”按钮的点击事件。
        """
        await self._handle_vote(interaction, 0)
