from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.models.StructuredSpeechMode import StructuredSpeechMode


class StructuredSpeechModeRepository:
    """封装模板发言模式表的数据库操作。"""

    def __init__(self, session: AsyncSession):
        """绑定当前工作单元的数据库会话。"""
        self.session = session

    async def get(self, thread_id: int) -> StructuredSpeechMode | None:
        """按帖子 ID 查询唯一模式记录。"""
        result = await self.session.exec(
            select(StructuredSpeechMode).where(StructuredSpeechMode.thread_id == thread_id)
        )
        return result.one_or_none()

    async def get_by_statuses(self, *statuses: str) -> list[StructuredSpeechMode]:
        """一次查询所有指定状态的模式记录。"""
        result = await self.session.exec(
            select(StructuredSpeechMode).where(col(StructuredSpeechMode.status).in_(statuses))
        )
        return list(result.all())

    async def save(self, mode: StructuredSpeechMode) -> StructuredSpeechMode:
        """新增或更新一条模式记录并刷新会话。"""
        self.session.add(mode)
        await self.session.flush()
        return mode
