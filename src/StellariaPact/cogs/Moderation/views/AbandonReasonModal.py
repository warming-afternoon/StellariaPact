import asyncio
import logging

import discord

from StellariaPact.cogs.Moderation.qo.AbandonProposalQo import \
    AbandonProposalQo
from StellariaPact.share.DiscordUtils import DiscordUtils
from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.StringUtils import StringUtils
from StellariaPact.share.UnitOfWork import UnitOfWork

from .ModerationEmbedBuilder import ModerationEmbedBuilder

logger = logging.getLogger(__name__)


class AbandonReasonModal(discord.ui.Modal):
    def __init__(self, bot: StellariaPactBot):
        super().__init__(title="废弃提案原因")
        self.bot = bot
        self.reason = discord.ui.TextInput(
            label="原因",
            style=discord.TextStyle.long,
            placeholder="请详细说明废弃此提案的原因...",
            required=True,
            max_length=4000,
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await self.bot.api_scheduler.submit(safeDefer(interaction, ephemeral=True), 1)

        if not isinstance(interaction.channel, discord.Thread):
            return await self.bot.api_scheduler.submit(
                interaction.followup.send("此命令只能在帖子内使用。", ephemeral=True), 1
            )

        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                qo = AbandonProposalQo(thread_id=interaction.channel.id, reason=self.reason.value)
                await uow.moderation.abandon_proposal(qo)
                await uow.commit()

        except ValueError as e:
            return await self.bot.api_scheduler.submit(
                interaction.followup.send(str(e), ephemeral=True), 1
            )

        # --- 事务外执行API调用 ---
        tasks = []

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

        # 准备更新帖子状态和标签
        clean_title = StringUtils.clean_title(interaction.channel.name)
        new_title = f"[已废弃] {clean_title}"
        edit_payload = {"name": new_title, "archived": True, "locked": True}

        if isinstance(interaction.channel.parent, discord.ForumChannel):
            new_tags = DiscordUtils.calculate_new_tags(
                current_tags=interaction.channel.applied_tags,
                forum_tags=interaction.channel.parent.available_tags,
                config=self.bot.config,
                target_tag_name="abandoned",
            )
            if new_tags is not None:
                edit_payload["applied_tags"] = new_tags

        await self.bot.api_scheduler.submit(interaction.channel.edit(**edit_payload), 2)

        # # 准备最终确认消息
        # tasks.append(
        #     self.bot.api_scheduler.submit(
        #         interaction.followup.send("提案已成功废弃。", ephemeral=True), 1
        #     )
        # )

        # 执行所有API调用
        await asyncio.gather(*tasks)
