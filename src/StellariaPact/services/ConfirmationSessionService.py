import logging
from typing import Optional

from sqlalchemy import update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Moderation.qo.CreateConfirmationSessionQo import (
    CreateConfirmationSessionQo,
)
from StellariaPact.models.ConfirmationSession import ConfirmationSession
from StellariaPact.share.enums.ConfirmationStatus import ConfirmationStatus

logger = logging.getLogger(__name__)


class ConfirmationSessionService:
    """
    提供处理确认会话相关数据库操作的服务。
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_confirmation_session(
        self, qo: CreateConfirmationSessionQo
    ) -> ConfirmationSession:
        """
        创建一个新的确认会话，并将发起者自动记录为第一个确认人。
        返回创建的 ConfirmationSession ORM 对象。
        """
        confirmed_parties = {}
        # 查找发起者拥有的、且此会话需要的第一个角色，并将其设为默认确认
        for role_key in qo.initiator_role_keys:
            if role_key in qo.required_roles:
                confirmed_parties[role_key] = qo.initiator_id
                break  # 只确认一个角色

        session = ConfirmationSession(
            context=qo.context,
            target_id=qo.target_id,
            message_id=qo.message_id,
            required_roles=qo.required_roles,
            confirmed_parties=confirmed_parties,
            reason=qo.reason,
        )
        self.session.add(session)
        await self.session.flush()
        await self.session.refresh(session)

        assert session.id is not None, "Session ID should not be None after flush"
        logger.debug(f"创建确认会话 {session.id}，上下文: {qo.context}")
        return session

    async def update_confirmation_session_message_id(self, session_id: int, message_id: int):
        """
        更新确认会话的消息ID。
        """
        statement = (
            update(ConfirmationSession)
            .where(ConfirmationSession.id == session_id)  # type: ignore
            .values(message_id=message_id)
        )
        await self.session.exec(statement)  # type: ignore
        logger.debug(f"更新确认会话 {session_id} 的消息ID为 {message_id}")

    async def get_confirmation_session_by_message_id(
        self, message_id: int
    ) -> Optional[ConfirmationSession]:
        """
        根据消息ID获取确认会话。
        """
        statement = select(ConfirmationSession).where(ConfirmationSession.message_id == message_id)
        result = await self.session.exec(statement)
        return result.one_or_none()

    async def add_confirmation(
        self, session: ConfirmationSession, role: str, user_id: int
    ) -> ConfirmationSession:
        """
        向确认会话添加一个确认方。
        """
        # 确保 confirmed_parties 是一个可修改的字典
        if session.confirmed_parties is None:
            session.confirmed_parties = {}

        # 创建副本以触发 SQLAlchemy 的变更检测
        new_confirmed_parties = session.confirmed_parties.copy()
        new_confirmed_parties[role] = user_id
        session.confirmed_parties = new_confirmed_parties

        # 检查是否所有角色都已确认
        if set(session.required_roles) == set(session.confirmed_parties.keys()):
            session.status = ConfirmationStatus.COMPLETED

        self.session.add(session)
        await self.session.flush()
        logger.debug(f"用户 {user_id} 确认了角色 {role}，会话 {session.id}")
        return session

    async def cancel_confirmation_session(
        self, session: ConfirmationSession, user_id: int
    ) -> ConfirmationSession:
        """
        取消一个确认会话。
        """
        session.status = ConfirmationStatus.CANCELED
        session.canceler_id = user_id
        self.session.add(session)
        await self.session.flush()
        logger.debug(f"用户 {user_id} 取消了确认会话 {session.id}")
        return session
