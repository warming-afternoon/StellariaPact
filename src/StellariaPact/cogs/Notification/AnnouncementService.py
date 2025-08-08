from datetime import datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Notification.dto.AnnouncementDto import AnnouncementDto
from StellariaPact.cogs.Notification.qo.CreateAnnouncementQo import \
    CreateAnnouncementQo
from StellariaPact.models.Announcement import Announcement


class AnnouncementService:
    """
    处理公示相关的业务逻辑。
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_announcement(self, qo: CreateAnnouncementQo) -> AnnouncementDto:
        """
        创建一条新的公示。

        Args:
            qo: 创建公示的查询对象。

        Returns:
            新创建的公示的数据传输对象。
        """
        new_announcement = Announcement(
            discussionThreadId=qo.discussionThreadId,
            announcerId=qo.announcerId,
            title=qo.title,
            content=qo.content,
            endTime=qo.endTime,
            status=1,  # 进行中
        )

        self.session.add(new_announcement)
        await self.session.flush()

        return AnnouncementDto.model_validate(new_announcement)

    async def get_by_thread_id(self, thread_id: int) -> AnnouncementDto | None:
        """
        通过讨论帖 ID 获取公示。

        Args:
            thread_id: 讨论帖的 ID。

        Returns:
            如果找到，则返回公示的数据传输对象，否则返回 None。
        """
        result = await self.session.exec(
            select(Announcement).where(Announcement.discussionThreadId == thread_id)
        )
        announcement = result.one_or_none()
        return AnnouncementDto.model_validate(announcement) if announcement else None

    async def get_expired_announcements(self) -> list[AnnouncementDto]:
        """
        获取所有已到期的公示。

        Returns:
            已到期的公示列表。
        """
        now = datetime.utcnow()
        result = await self.session.exec(
            select(Announcement).where(Announcement.endTime <= now, Announcement.status == 1)
        )
        expired = result.all()
        return [AnnouncementDto.model_validate(ann) for ann in expired]

    async def update_end_time(self, announcement_id: int, new_end_time: datetime):
        """
        更新特定公示的结束时间。

        Args:
            announcement_id: 要更新的公示的 ID。
            new_end_time: 新的结束时间。
        """
        announcement = await self.session.get(Announcement, announcement_id)
        if announcement:
            announcement.endTime = new_end_time
            self.session.add(announcement)

    async def mark_announcement_as_finished(self, announcement_id: int):
        """
        将单个公示标记为已结束。

        Args:
            announcement_id: 要标记的公示的 ID。
        """
        announcement = await self.session.get(Announcement, announcement_id)
        if announcement:
            announcement.status = 0  # 已结束
            self.session.add(announcement)
