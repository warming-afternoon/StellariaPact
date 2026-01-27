from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from StellariaPact.services.AnnouncementMonitorService import AnnouncementMonitorService
    from StellariaPact.services.AnnouncementService import AnnouncementService
    from StellariaPact.services.ConfirmationSessionService import ConfirmationSessionService
    from StellariaPact.services.ObjectionService import ObjectionService
    from StellariaPact.services.ProposalService import ProposalService
    from StellariaPact.services.UserActivityService import UserActivityService
    from StellariaPact.services.UserVoteService import UserVoteService
    from StellariaPact.services.VoteOptionService import VoteOptionService
    from StellariaPact.services.VoteSessionService import VoteSessionService
    from StellariaPact.share.DatabaseHandler import DatabaseHandler


logger = logging.getLogger(__name__)


class UnitOfWork:
    """
    一个实现了工作单元模式的异步上下文管理器。

    它封装了数据库会话和事务管理，并提供了对各个服务（仓库）的访问<br>
    这确保了在单个业务操作中的所有数据库更改要么一起提交，要么一起回滚。

    用法:<br>
    async with UnitOfWork() as uow:<br>
        await uow.announcements.create_announcement(...)<br>
        await uow.commit()<br>
    """

    def __init__(self, db_handler: Optional["DatabaseHandler"]):
        self._db_handler = db_handler
        self._session: Optional[AsyncSession] = None
        self._committed = False

    async def __aenter__(self) -> "UnitOfWork":
        """在进入上下文时，获取一个新的数据库会话。"""
        if self._db_handler is None:
            raise RuntimeError(
                "UnitOfWork 在没有有效 DatabaseHandler 的情况下被使用。"
                "请确保 bot.db_handler 已在 setup_hook 中正确初始化。"
            )
        self._session = self._db_handler.get_session()
        self._committed = False  # 重置提交标志
        # 在这里，我们延迟服务的实例化，直到第一次访问它们
        # 这样可以避免在不需要时创建服务实例
        return self

    async def __aexit__(self, exc_type, exc_val, traceback):
        """
        在退出上下文时，根据是否发生异常来提交或回滚事务，并最终关闭会话。
        """
        if not self._session:
            return

        try:
            if exc_type:
                # 如果发生异常，记录并回滚
                if not self._committed:
                    logger.warning(
                        f"UnitOfWork 检测到异常，正在回滚事务: {exc_type.__name__}: {exc_val}"
                    )
                    await self.rollback()
            else:
                # 如果没有异常且未手动提交，提交
                if not self._committed:
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
        self._committed = True

    async def rollback(self):
        """回滚当前事务。"""
        await self.session.rollback()
        self._committed = True

    async def flush(self, objects=None):
        """
        将当前会话中的挂起更改刷新到数据库。
        这对于在提交前获取数据库生成的默认值（如自增ID）非常有用。
        """
        await self.session.flush(objects)

    # --- 服务/仓库访问属性 ---

    @property
    def vote_session(self) -> "VoteSessionService":
        """获取投票会话服务实例。"""
        if not hasattr(self, "_vote_session_service"):
            from StellariaPact.services.VoteSessionService import VoteSessionService

            self._vote_session_service = VoteSessionService(self.session)
        return self._vote_session_service

    @property
    def announcements(self) -> "AnnouncementService":
        """获取公示服务实例。"""
        if not hasattr(self, "_announcement_service"):
            from StellariaPact.services.AnnouncementService import AnnouncementService

            self._announcement_service = AnnouncementService(self.session)
        return self._announcement_service

    @property
    def announcement_monitors(self) -> "AnnouncementMonitorService":
        """获取公示监控服务实例。"""
        if not hasattr(self, "_announcement_monitor_service"):
            from StellariaPact.services.AnnouncementMonitorService import (
                AnnouncementMonitorService,
            )

            self._announcement_monitor_service = AnnouncementMonitorService(self.session)
        return self._announcement_monitor_service

    @property
    def objection(self) -> "ObjectionService":
        """获取异议服务实例。"""
        if not hasattr(self, "_objection_service"):
            from StellariaPact.services.ObjectionService import ObjectionService

            self._objection_service = ObjectionService(self.session)
        return self._objection_service

    @property
    def user_activity(self) -> "UserActivityService":
        """获取用户活动服务实例。"""
        if not hasattr(self, "_user_activity_service"):
            from StellariaPact.services.UserActivityService import UserActivityService

            self._user_activity_service = UserActivityService(self.session)
        return self._user_activity_service

    @property
    def user_vote(self) -> "UserVoteService":
        """获取用户投票服务实例。"""
        if not hasattr(self, "_user_vote_service"):
            from StellariaPact.services.UserVoteService import UserVoteService

            self._user_vote_service = UserVoteService(self.session)
        return self._user_vote_service

    @property
    def vote_option(self) -> "VoteOptionService":
        """获取投票选项服务实例。"""
        if not hasattr(self, "_vote_option_service"):
            from StellariaPact.services.VoteOptionService import VoteOptionService

            self._vote_option_service = VoteOptionService(self.session)
        return self._vote_option_service

    @property
    def confirmation_session(self) -> "ConfirmationSessionService":
        """获取确认会话服务实例。"""
        if not hasattr(self, "_confirmation_session_service"):
            from StellariaPact.services.ConfirmationSessionService import (
                ConfirmationSessionService,
            )

            self._confirmation_session_service = ConfirmationSessionService(self.session)
        return self._confirmation_session_service

    @property
    def proposal(self) -> "ProposalService":
        """获取提案服务实例。"""
        if not hasattr(self, "_proposal_service"):
            from StellariaPact.services.ProposalService import ProposalService

            self._proposal_service = ProposalService(self.session)
        return self._proposal_service
