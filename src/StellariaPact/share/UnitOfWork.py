from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from StellariaPact.cogs.Notification.AnnouncementMonitorService import (
        AnnouncementMonitorService,
    )
    from StellariaPact.cogs.Notification.AnnouncementService import AnnouncementService
    from StellariaPact.cogs.Voting.VotingService import VotingService
    from StellariaPact.share.DatabaseHandler import DatabaseHandler


logger = logging.getLogger(__name__)


class UnitOfWork:
    """
    一个实现了工作单元模式的异步上下文管理器。

    它封装了数据库会话和事务管理，并提供了对各个服务（仓库）的访问。
    这确保了在单个业务操作中的所有数据库更改要么一起提交，要么一起回滚。

    用法:
    async with UnitOfWork() as uow:
        await uow.voting.record_user_vote(...)
        await uow.announcements.create_announcement(...)
        await uow.commit()
    """

    def __init__(self, db_handler: Optional["DatabaseHandler"]):
        self._db_handler = db_handler
        self._session: Optional[AsyncSession] = None

    async def __aenter__(self) -> "UnitOfWork":
        """在进入上下文时，获取一个新的数据库会话。"""
        if self._db_handler is None:
            raise RuntimeError(
                "UnitOfWork 在没有有效 DatabaseHandler 的情况下被使用。"
                "请确保 bot.db_handler 已在 setup_hook 中正确初始化。"
            )
        self._session = self._db_handler.get_session()
        # 在这里，我们延迟服务的实例化，直到第一次访问它们
        # 这样可以避免在不需要时创建服务实例
        return self

    async def __aexit__(self, exc_type, exc_val, traceback):
        """
        在退出上下文时，根据是否发生异常来提交或回滚事务，并最终关闭会话。
        """
        if self._session:
            try:
                if exc_type:
                    logger.warning(
                        f"UnitOfWork 因异常退出，正在回滚事务: {exc_type.__name__}: {exc_val}"
                    )
                    await self.rollback()
                else:
                    # 如果 with 块正常完成，则自动提交
                    await self.commit()
            finally:
                # 确保会话总是被关闭
                await self._session.close()
                self._session = None

    @property
    def session(self) -> AsyncSession:
        """获取当前的数据库会话。"""
        if self._session is None:
            raise RuntimeError("会话尚未初始化。请在 'async with' 块中使用 UnitOfWork。")
        return self._session

    async def commit(self):
        """提交当前事务。"""
        await self.session.commit()

    async def rollback(self):
        """回滚当前事务。"""
        await self.session.rollback()

    # --- 服务/仓库访问属性 ---

    @property
    def voting(self) -> "VotingService":
        """获取投票服务实例。"""
        # 懒加载：只在第一次访问时创建服务实例
        if not hasattr(self, "_voting_service"):
            from StellariaPact.cogs.Voting.VotingService import VotingService

            self._voting_service = VotingService(self.session)
        return self._voting_service

    @property
    def announcements(self) -> "AnnouncementService":
        """获取公示服务实例。"""
        if not hasattr(self, "_announcement_service"):
            from StellariaPact.cogs.Notification.AnnouncementService import AnnouncementService

            self._announcement_service = AnnouncementService(self.session)
        return self._announcement_service

    @property
    def announcement_monitors(self) -> "AnnouncementMonitorService":
        """获取公示监控服务实例。"""
        if not hasattr(self, "_announcement_monitor_service"):
            from StellariaPact.cogs.Notification.AnnouncementMonitorService import (
                AnnouncementMonitorService,
            )

            self._announcement_monitor_service = AnnouncementMonitorService(self.session)
        return self._announcement_monitor_service
