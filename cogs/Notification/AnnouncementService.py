from datetime import datetime
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from models.Announcement import Announcement
from .qo.CreateAnnouncementQo import CreateAnnouncementQo
from .dto.AnnouncementDto import AnnouncementDto

class AnnouncementService:
    """
    处理公示相关的业务逻辑。
    """

    async def create_announcement(self, session: AsyncSession, qo: CreateAnnouncementQo) -> AnnouncementDto:
        """
        创建一条新的公示。

        Args:
            session: 数据库会话。
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
            status=0  # 0: 进行中
        )
        
        session.add(new_announcement)
        await session.commit()
        await session.refresh(new_announcement)
        
        return AnnouncementDto.from_orm(new_announcement)

    async def get_expired_announcements(self, session: AsyncSession) -> list[AnnouncementDto]:
        """
        获取所有已到期的公示。

        Args:
            session: 数据库会话。

        Returns:
            已到期的公示列表。
        """
        now = datetime.utcnow()
        result = await session.exec(
            select(Announcement).where(Announcement.endTime <= now, Announcement.status == 0)
        )
        expired = result.all()
        return [AnnouncementDto.from_orm(ann) for ann in expired]

    async def mark_announcement_as_finished(self, session: AsyncSession, announcement_id: int):
        """
        将单个公示标记为已结束。

        Args:
            session: 数据库会话。
            announcement_id: 要标记的公示的 ID。
        """
        announcement = await session.get(Announcement, announcement_id)
        if announcement:
            announcement.status = 1  # 1: 已结束
            session.add(announcement)
            await session.commit()