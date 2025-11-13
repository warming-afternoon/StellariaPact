import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import discord
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.models.Announcement import Announcement
from StellariaPact.models.AnnouncementChannelMonitor import AnnouncementChannelMonitor
from StellariaPact.share.StellariaPactBot import StellariaPactBot

from .AnnouncementMonitorService import AnnouncementMonitorService
from .views.AnnouncementEmbedBuilder import AnnouncementEmbedBuilder

logger = logging.getLogger(__name__)


class RepostService:
    """
    处理与重复播报相关的业务逻辑。
    """

    def __init__(
        self,
        bot: StellariaPactBot,
        session: AsyncSession,
    ):
        self.bot = bot
        self.session = session
        self.monitor_service = AnnouncementMonitorService(session)

    async def process_single_repost(self, monitor: AnnouncementChannelMonitor) -> None:
        """
        处理单个重复播报操作：发送消息并更新数据库。
        如果发生任何错误，将引发异常，由调用方 (后台任务) 捕获和处理。
        """
        logger.debug(f"开始处理单个重复播报，监控器 ID: {monitor.id}...")

        # 获取主公示信息
        announcement = await self.session.get(Announcement, monitor.announcement_id)
        if not announcement:
            logger.warning(
                f"监控器 (ID: {monitor.id}) 指向的公示 "
                f"(Ann ID: {monitor.announcement_id}) 不存在。正在删除此孤立监控器。"
            )
            await self.session.delete(monitor)
            return

        if announcement.status != 1:
            logger.warning(
                f"监控器 (ID: {monitor.id}) 指向的公示 (Ann ID: {monitor.announcement_id}) "
                "状态不是“进行中”。跳过重复播报。"
            )
            return

        # 获取所需 Discord 对象 (如果找不到会引发异常)
        logger.debug(f"正在为监控器 {monitor.id} 获取 Discord 对象...")
        channel = self.bot.get_channel(monitor.channel_id) or await self.bot.fetch_channel(
            monitor.channel_id
        )
        if not isinstance(channel, discord.TextChannel):
            # 这是一种不太可能发生但需要处理的边缘情况
            logger.error(f"获取到的频道 (ID: {monitor.channel_id}) 不是有效的文本频道。")
            raise TypeError(f"Channel {monitor.channel_id} is not a TextChannel.")

        author = self.bot.get_user(announcement.announcer_id) or await self.bot.fetch_user(
            announcement.announcer_id
        )
        logger.debug(f"成功获取频道 {channel.name} 和作者 {author.name}。")

        # 构建并发送消息
        logger.debug(f"正在为监控器 {monitor.id} 构建并发送 embed...")
        thread_url = f"https://discord.com/channels/{self.bot.config['guild_id']}/{announcement.discussion_thread_id}"
        utc_end_time = announcement.end_time.replace(tzinfo=ZoneInfo("UTC"))
        discord_timestamp = (
            f"<t:{int(utc_end_time.timestamp())}:F> (<t:{int(utc_end_time.timestamp())}:R>)"
        )

        embed = AnnouncementEmbedBuilder.create_announcement_embed(
            title=announcement.title,
            content=announcement.content,
            thread_url=thread_url,
            discord_timestamp=discord_timestamp,
            author=author,
            start_time_utc=announcement.created_at.replace(tzinfo=ZoneInfo("UTC")),
            is_repost=True,
        )

        await self.bot.api_scheduler.submit(coro=channel.send(embed=embed), priority=5)
        logger.info(f"已提交API请求，在频道 {channel.id} 重播公示 {announcement.id}。")

        # 更新监控器状态
        logger.debug(f"正在更新监控器 {monitor.id} 的数据库状态...")
        monitor.message_count_since_last = 0
        monitor.last_repost_at = datetime.now(timezone.utc)
        self.session.add(monitor)
        logger.debug(f"成功在频道 {monitor.channel_id} 重播了公示 {monitor.announcement_id}。")
