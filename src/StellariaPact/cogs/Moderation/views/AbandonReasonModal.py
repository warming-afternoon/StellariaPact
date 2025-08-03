import asyncio
import logging

import discord

from StellariaPact.cogs.Moderation.qo.AbandonProposalQo import AbandonProposalQo
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
        tasks.append(self.bot.api_scheduler.submit(interaction.channel.send(embed=embed), 1))

        # 准备更新帖子状态和标签
        edit_task = None
        clean_title = StringUtils.clean_title(interaction.channel.name)
        new_title = f"[已废弃] {clean_title}"
        if isinstance(interaction.channel.parent, discord.ForumChannel):
            try:
                abandoned_tag = discord.utils.get(
                    interaction.channel.parent.available_tags, name="已废弃"
                )
                if abandoned_tag:
                    edit_task = self.bot.api_scheduler.submit(
                        interaction.channel.edit(
                            name=new_title,
                            archived=True,
                            locked=True,
                            applied_tags=[abandoned_tag],
                        ),
                        2,
                    )
            except Exception as e:
                logger.warning(f"查找'已废弃'标签时出错: {e}", exc_info=True)

        if not edit_task:
            edit_task = self.bot.api_scheduler.submit(
                interaction.channel.edit(name=new_title, archived=True, locked=True), 2
            )
        tasks.append(edit_task)

        # 准备最终确认消息
        tasks.append(
            self.bot.api_scheduler.submit(
                interaction.followup.send("提案已成功废弃。", ephemeral=True), 1
            )
        )

        # 执行所有API调用
        await asyncio.gather(*tasks)
