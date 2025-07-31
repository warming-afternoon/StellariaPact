import asyncio
import logging

import discord
from discord.ext import commands

from StellariaPact.cogs.Voting.views.VoteView import VoteView
from StellariaPact.cogs.Voting.VotingService import VotingService
from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


class ThreadListener(commands.Cog):
    def __init__(self, bot: StellariaPactBot, voting_service: VotingService):
        self.bot = bot
        self.voting_service = voting_service

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        """
        监听新帖子的创建。
        """
        # 检查帖子是否在指定的讨论频道中
        discussion_channel_id = self.bot.config.get("channels", {}).get("discussion")
        if not discussion_channel_id or thread.parent_id != int(
            discussion_channel_id
        ):
            return

        # 等待一小段时间，确保帖子完全创建
        await asyncio.sleep(0.5)

        logger.info(f"在新帖子 '{thread.name}' (ID: {thread.id}) 中创建投票面板。")

        try:
            # 创建投票会话
            async with self.bot.db_handler.get_session() as session:
                await self.voting_service.create_vote_session(session, thread.id)

            # 创建视图和嵌入消息
            view = VoteView(self.bot, self.voting_service)
            embed = discord.Embed(
                title="投票面板",
                description="点击下方按钮，对本提案进行投票。",
                color=discord.Color.blue(),
            )
            embed.set_footer(text="投票资格：在本帖内有效发言数 ≥ 3")

            # 发送消息
            await self.bot.api_scheduler.submit(
                thread.send(embed=embed, view=view), priority=5
            )
        except Exception as e:
            logger.error(
                f"无法在帖子 {thread.id} 中创建投票面板: {e}", exc_info=True
            )
