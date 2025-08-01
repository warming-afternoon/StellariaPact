import logging

import discord
from discord.ext import commands
from sqlalchemy import func, select, update

from StellariaPact.models.Announcement import Announcement
from StellariaPact.models.AnnouncementChannelMonitor import AnnouncementChannelMonitor
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.UnitOfWork import UnitOfWork

logger = logging.getLogger(__name__)


class AnnounceMessageListener(commands.Cog):
    """
    监听消息以更新重复公示的计数器。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.monitored_channels: set[int] | None = None

    async def load_monitored_channels(self):
        """从数据库加载所有当前被监控的频道ID。"""
        logger.info("正在从数据库加载被监控的频道列表...")
        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                stmt = select(func.distinct(AnnouncementChannelMonitor.channelId))
                result = await uow.session.execute(stmt)
                self.monitored_channels = {row[0] for row in result.fetchall()}
                logger.info(f"加载了 {len(self.monitored_channels)} 个被监控的频道。")
        except Exception as e:
            logger.error(f"加载被监控频道时发生错误: {e}", exc_info=True)
            # 即使失败，也初始化为空集合以防止重复加载
            if self.monitored_channels is None:
                self.monitored_channels = set()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        当有新消息时，如果其所在频道是被监控的，则增加其计数器。
        """
        # 惰性加载：如果监控列表尚未加载，则先加载它
        if self.monitored_channels is None:
            await self.load_monitored_channels()

        if (
            message.author.bot
            or not self.monitored_channels
            or message.channel.id not in self.monitored_channels
        ):
            return

        async with UnitOfWork(self.bot.db_handler) as uow:
            stmt = (
                update(AnnouncementChannelMonitor)
                .where(
                    AnnouncementChannelMonitor.channelId == message.channel.id,  # type: ignore
                    AnnouncementChannelMonitor.announcementId.in_(  # type: ignore
                        select(Announcement.id).where(Announcement.status == 1)  # type: ignore
                    ),
                )
                .values(messageCountSinceLast=AnnouncementChannelMonitor.messageCountSinceLast + 1)
                .execution_options(synchronize_session=False)
            )
            await uow.session.execute(stmt)
