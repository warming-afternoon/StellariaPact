import asyncio
import logging
import random
from collections import defaultdict
from typing import DefaultDict

import discord
from discord.ext import commands, tasks
from sqlalchemy import func, select, update

from StellariaPact.models.Announcement import Announcement
from StellariaPact.models.AnnouncementChannelMonitor import AnnouncementChannelMonitor
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.UnitOfWork import UnitOfWork

logger = logging.getLogger(__name__)


class AnnounceMessageListener(commands.Cog):
    """
    通过内存缓存和后台批量更新，监听消息以更新重复公示的计数器。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.monitored_channels: set[int] | None = None
        # 内存缓存: {channel_id: message_count_increment}
        self.message_cache: DefaultDict[int, int] = defaultdict(int)
        self.cache_lock = asyncio.Lock()

    def cog_unload(self):
        """在 Cog 卸载时，确保缓存被写入数据库。"""
        if self.update_cache_to_db.is_running():
            self.update_cache_to_db.cancel()
        # 尝试同步执行一次最后的写入
        try:
            # 创建一个新的事件循环来运行异步的 flush 操作
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.flush_message_cache())
            loop.close()
        except Exception as e:
            logger.error(f"在 cog_unload 期间同步刷新缓存失败: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_ready(self):
        """当 Cog 准备就绪时，加载监控频道并启动后台任务。"""
        await self.load_monitored_channels()
        self.update_cache_to_db.start()

    @tasks.loop(seconds=60)
    async def update_cache_to_db(self):
        """后台任务，定期将内存中的消息计数缓存写入数据库。"""
        await self.flush_message_cache()

    async def flush_message_cache(self):
        """将缓存数据写入数据库的核心逻辑。"""
        async with self.cache_lock:
            if not self.message_cache:
                return

            # 复制缓存内容以进行处理，然后立即清空原始缓存
            # 这样可以减少锁定的时间
            cache_to_flush = self.message_cache.copy()
            self.message_cache.clear()

        logger.debug(f"正在将 {len(cache_to_flush)} 个频道的缓存消息计数写入数据库...")
        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                for channel_id, increment in cache_to_flush.items():
                    # 找到所有在该频道中处于活动状态的监控器
                    active_monitors_stmt = (
                        select(AnnouncementChannelMonitor.id)  # type: ignore
                        .join(Announcement)
                        .where(
                            AnnouncementChannelMonitor.channelId == channel_id,
                            Announcement.status == 1,
                        )
                    )
                    result = await uow.session.execute(active_monitors_stmt)
                    monitor_ids = [row[0] for row in result.fetchall()]

                    if not monitor_ids:
                        continue

                    # 为这些监控器批量增加计数值
                    stmt = (
                        update(AnnouncementChannelMonitor)
                        .where(AnnouncementChannelMonitor.id.in_(monitor_ids))  # type: ignore
                        .values(
                            messageCountSinceLast=AnnouncementChannelMonitor.messageCountSinceLast
                            + increment
                        )
                        .execution_options(synchronize_session=False)
                    )
                    await uow.session.execute(stmt)
                await uow.commit()
            logger.debug("缓存消息计数成功写入数据库。")
        except Exception as e:
            logger.error(f"更新消息计数缓存到数据库时发生错误: {e}", exc_info=True)
            # 如果失败，可以考虑将 cache_to_flush 的内容重新加回到 self.message_cache 中
            # 以便下次重试，但这可能会导致更复杂的状态管理
            async with self.cache_lock:
                for channel_id, increment in cache_to_flush.items():
                    self.message_cache[channel_id] += increment

    async def load_monitored_channels(self):
        """从数据库加载所有当前被监控的频道ID。"""
        logger.debug("正在从数据库加载被监控的频道列表...")
        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                stmt = select(func.distinct(AnnouncementChannelMonitor.channelId))
                result = await uow.session.execute(stmt)
                self.monitored_channels = {row[0] for row in result.fetchall()}
                logger.debug(f"加载了 {len(self.monitored_channels)} 个被监控的频道。")
        except Exception as e:
            logger.error(f"加载被监控频道时发生错误: {e}", exc_info=True)
            if self.monitored_channels is None:
                self.monitored_channels = set()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        当有新消息时，如果其所在频道是被监控的，则在内存缓存中增加其计数器。
        """
        if self.monitored_channels is None:
            # 如果尚未加载，则不处理消息，等待 on_ready 完成加载
            return

        if (
            message.author.bot
            or not self.monitored_channels
            or message.channel.id not in self.monitored_channels
        ):
            return

        async with self.cache_lock:
            self.message_cache[message.channel.id] += 1

    @update_cache_to_db.before_loop
    async def before_update_cache(self):
        """在循环开始前，等待机器人准备就绪。"""
        await self.bot.wait_until_ready()
        # 增加随机延迟以错开任务启动时间
        await asyncio.sleep(random.randint(0, 10))
