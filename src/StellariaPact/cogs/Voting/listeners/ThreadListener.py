import asyncio
import logging
import re

import discord
from discord.ext import commands

from StellariaPact.cogs.Voting.qo.CreateVoteSessionQo import \
    CreateVoteSessionQo
from StellariaPact.cogs.Voting.views.VoteEmbedBuilder import VoteEmbedBuilder
from StellariaPact.cogs.Voting.views.VoteView import VoteView
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.TimeUtils import TimeUtils
from StellariaPact.share.UnitOfWork import UnitOfWork

logger = logging.getLogger(__name__)


class ThreadListener(commands.Cog):
    def __init__(self, bot: StellariaPactBot):
        self.bot = bot

    async def _dispatch_proposal_creation(self, thread: discord.Thread):
        """
        从帖子的启动消息中解析出提案人ID，并分派事件。
        """
        try:
            # 优先使用缓存的启动消息，避免不必要的API调用
            start_message = thread.starter_message
            if not start_message:
                # 如果缓存中没有，再尝试通过API获取
                logger.debug(f"帖子 {thread.id} 的启动消息不在缓存中，尝试API获取...")
                start_message = await thread.fetch_message(thread.id)

            if not start_message:
                logger.warning(f"无法获取帖子 {thread.id} 的启动消息。")
                return

            # 使用正则表达式从消息内容中解析出用户ID
            match = re.search(r"<@(\d+)>", start_message.content)
            if match:
                proposer_id = int(match.group(1))
                self.bot.dispatch("proposal_thread_created", thread.id, proposer_id)
            else:
                logger.warning(f"在帖子 {thread.id} 的启动消息中未找到提案人ID。")

        except discord.NotFound:
            logger.warning(f"无法找到帖子 {thread.id} 的启动消息，可能已被删除。")
        except Exception as e:
            logger.error(f"解析提案人ID时发生错误 (帖子ID: {thread.id}): {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        """
        监听新帖子的创建，分派提案创建事件，并创建投票面板。
        """
        # 检查帖子是否在指定的讨论频道中
        discussion_channel_id = self.bot.config.get("channels", {}).get("discussion")
        if not discussion_channel_id or thread.parent_id != int(discussion_channel_id):
            return

        # 等待一小段时间，确保帖子完全创建
        await asyncio.sleep(0.5)
        
        # 分派创建提案的事件
        asyncio.create_task(self._dispatch_proposal_creation(thread))


        logger.info(f"在新帖子 '{thread.name}' (ID: {thread.id}) 中创建投票面板。")

        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                # 准备参数和 View
                target_tz = self.bot.config.get("timezone", "UTC")
                end_time = TimeUtils.get_utc_end_time(duration_hours=72, target_tz=target_tz)
                view = VoteView(self.bot)

                # 使用 Builder 构建 Embed
                embed = VoteEmbedBuilder.create_initial_vote_embed(
                    topic=thread.name,
                    author=None,  # 自动创建的投票没有明确的发起人
                    realtime=True,
                    anonymous=True,
                    end_time=end_time,
                )

                # 发送消息并获取返回的 message 对象
                message = await self.bot.api_scheduler.submit(
                    thread.send(embed=embed, view=view), priority=5
                )

                # 存入数据库
                qo = CreateVoteSessionQo(
                    thread_id=thread.id,
                    context_message_id=message.id,
                    realtime=True,
                    anonymous=True,
                    end_time=end_time,
                )
                await uow.voting.create_vote_session(qo)
                await uow.commit()
        except Exception as e:
            logger.error(f"无法在帖子 {thread.id} 中创建投票面板: {e}", exc_info=True)
