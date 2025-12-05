import asyncio
import logging

import discord

from StellariaPact.cogs.Moderation.qo.AbandonProposalQo import AbandonProposalQo
from StellariaPact.cogs.Moderation.thread_manager import ProposalThreadManager
from StellariaPact.cogs.Moderation.views.ModerationEmbedBuilder import ModerationEmbedBuilder
from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.StringUtils import StringUtils
from StellariaPact.share.UnitOfWork import UnitOfWork

logger = logging.getLogger(__name__)


class AbandonReasonModal(discord.ui.Modal):
    def __init__(
        self, bot: StellariaPactBot, thread_manager: ProposalThreadManager
    ):  # 修改构造函数
        super().__init__(title="废弃提案原因")
        self.bot = bot
        self.thread_manager = thread_manager
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

        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                qo = AbandonProposalQo(thread_id=interaction.channel.id, reason=self.reason.value)
                await uow.proposal.abandon_proposal(qo)
                await uow.commit()

        except ValueError as e:
            return await self.bot.api_scheduler.submit(
                interaction.followup.send(str(e), ephemeral=True), 1
            )

        # --- 事务外执行API调用 ---

        # 准备公示Embed
        clean_title_for_embed = StringUtils.clean_title(interaction.channel.name)
        embed = ModerationEmbedBuilder.build_status_change_embed(
            thread_name=clean_title_for_embed,
            new_status="已废弃",
            moderator=interaction.user,
            reason=self.reason.value,
        )
        await self.bot.api_scheduler.submit(interaction.channel.send(embed=embed), 1)
        await asyncio.sleep(0.05)

        await self.thread_manager.update_status(interaction.channel, "abandoned")
