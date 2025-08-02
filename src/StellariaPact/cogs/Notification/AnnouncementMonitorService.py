from datetime import datetime, timezone

from sqlalchemy import and_, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.models.Announcement import Announcement
from StellariaPact.models.AnnouncementChannelMonitor import AnnouncementChannelMonitor


class AnnouncementMonitorService:
    """
    处理公示监控相关的业务逻辑。
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_pending_reposts(self) -> list[AnnouncementChannelMonitor]:
        """
        获取所有满足重复播报条件的监控器。
        """
        now_utc = datetime.now(timezone.utc)

        # 使用特定于数据库的函数将时间转换为 Unix 时间戳（整数秒）进行比较，
        # 以绕过 SQLAlchemy 对 timedelta 和列进行复杂运算时的翻译问题
        from sqlalchemy import func

        current_timestamp = func.strftime("%s", now_utc)
        last_repost_timestamp = func.strftime("%s", AnnouncementChannelMonitor.lastRepostAt)
        required_seconds_interval = AnnouncementChannelMonitor.timeIntervalMinutes * 60

        time_check_clause = current_timestamp - last_repost_timestamp >= required_seconds_interval

        stmt = (
            select(AnnouncementChannelMonitor)
            .join(Announcement, Announcement.id == AnnouncementChannelMonitor.announcementId)  # type: ignore
            .where(
                and_(
                    Announcement.status == 1,  # type: ignore
                    AnnouncementChannelMonitor.messageCountSinceLast
                    >= AnnouncementChannelMonitor.messageThreshold,  # type: ignore
                    time_check_clause,  # type: ignore
                )
            )
        )
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def create_monitors_for_announcement(
        self,
        announcement_id: int,
        channel_ids: list[int],
        message_threshold: int,
        time_interval_minutes: int,
    ):
        """
        为一个公示批量创建频道监控器。
        """
        for channel_id in channel_ids:
            monitor = AnnouncementChannelMonitor(
                announcementId=announcement_id,
                channelId=channel_id,
                messageThreshold=message_threshold,
                timeIntervalMinutes=time_interval_minutes,
            )
            self.session.add(monitor)

    async def delete_monitors_for_announcement(self, announcement_id: int):
        """
        批量删除与特定公示相关的所有监控器记录。
        """
        stmt = delete(AnnouncementChannelMonitor).where(
            AnnouncementChannelMonitor.announcementId == announcement_id  # type: ignore
        )
        await self.session.execute(stmt)
