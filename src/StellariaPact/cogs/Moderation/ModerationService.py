import logging
from typing import Optional

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Moderation.dto.ConfirmationSessionDto import ConfirmationSessionDto
from StellariaPact.cogs.Moderation.qo.AbandonProposalQo import AbandonProposalQo
from StellariaPact.cogs.Moderation.qo.CreateConfirmationSessionQo import (
    CreateConfirmationSessionQo,
)
from StellariaPact.models.ConfirmationSession import ConfirmationSession
from StellariaPact.models.Proposal import Proposal
from StellariaPact.models.UserActivity import UserActivity

logger = logging.getLogger(__name__)


class ModerationService:
    """
    提供处理议事管理相关业务逻辑的服务。
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_user_activity(self, user_id: int, thread_id: int) -> Optional[UserActivity]:
        """
        获取用户在特定帖子中的活动记录。

        Args:
            user_id: 用户的Discord ID。
            thread_id: 上下文的帖子ID。

        Returns:
            如果找到则返回 UserActivity 对象，否则返回 None。
        """
        statement = select(UserActivity).where(
            UserActivity.userId == user_id,
            UserActivity.contextThreadId == thread_id,
        )
        result = await self.session.exec(statement)
        return result.one_or_none()

    async def update_user_validation_status(
        self, user_id: int, thread_id: int, is_valid: bool
    ) -> UserActivity:
        """
        更新用户在特定帖子中的投票有效性状态。
        如果记录不存在，则会创建一条新记录。

        Args:
            user_id: 用户的Discord ID。
            thread_id: 上下文的帖子ID。
            is_valid: 用户投票是否有效。

        Returns:
            返回被创建或更新的 UserActivity 对象。
        """
        # 尝试获取现有的活动记录
        user_activity = await self.get_user_activity(user_id, thread_id)

        if user_activity:
            # 如果记录存在，则更新其状态
            user_activity.validation = 1 if is_valid else 0
        else:
            # 如果记录不存在，则创建一条新记录
            user_activity = UserActivity(
                userId=user_id,
                contextThreadId=thread_id,
                validation=1 if is_valid else 0,
            )

        self.session.add(user_activity)
        await self.session.flush()
        return user_activity

    async def create_proposal(self, thread_id: int, proposer_id: int) -> None:
        """
        尝试创建一个新的提案，如果因唯一性约束而失败，则静默处理。

        Args:
            thread_id: 提案讨论帖的ID。
            proposer_id: 提案发起人的ID。
        """
        new_proposal = Proposal(discussionThreadId=thread_id, proposerId=proposer_id, status=0)
        self.session.add(new_proposal)
        try:
            await self.session.flush()
            logger.debug(f"成功为帖子 {thread_id} 创建新的提案，发起人: {proposer_id}")
        except IntegrityError:
            # 捕获违反唯一约束的错误，意味着提案已存在
            logger.debug(f"提案 (帖子ID: {thread_id}) 已存在，无需重复创建。回滚会话。")
            # 发生错误时，SQLAlchemy 会话会自动回滚，
            # 我们只需确保操作可以安全地继续。
            await self.session.rollback()

    async def update_proposal_status_by_thread_id(self, thread_id: int, status: int):
        """
        根据帖子ID更新提案的状态。

        Args:
            thread_id: 讨论帖的ID。
            status: 新的状态值。
        """
        statement = (
            update(Proposal)
            .where(Proposal.discussionThreadId == thread_id)  # type: ignore
            .values(status=status)
            .returning(Proposal.id)  # type: ignore
        )
        result = await self.session.exec(statement)
        updated_id = result.scalar_one_or_none()

        if updated_id is not None:
            logger.debug(
                f"已将帖子 {thread_id} (Proposal ID: {updated_id}) 的提案状态更新为 {status}。"
            )
        else:
            logger.warning(f"尝试更新状态时，未找到帖子 {thread_id} 关联的提案。")

    async def get_proposal_by_thread_id(self, thread_id: int) -> Optional[Proposal]:
        """
        根据帖子ID获取提案。
        """
        statement = select(Proposal).where(Proposal.discussionThreadId == thread_id)
        result = await self.session.exec(statement)
        return result.one_or_none()

    async def get_proposal_by_id(self, proposal_id: int) -> Optional[Proposal]:
        """
        根据提案ID获取提案。
        """
        return await self.session.get(Proposal, proposal_id)

    async def create_confirmation_session(
        self, qo: CreateConfirmationSessionQo
    ) -> ConfirmationSessionDto:
        """
        创建一个新的确认会话，并将发起者自动记录为第一个确认人。
        """
        confirmed_parties = {}
        # 查找发起者拥有的、且此会话需要的第一个角色，并将其设为默认确认
        for role_key in qo.initiator_role_keys:
            if role_key in qo.required_roles:
                confirmed_parties[role_key] = qo.initiator_id
                break  # 只确认一个角色

        session = ConfirmationSession(
            context=qo.context,
            targetId=qo.target_id,
            messageId=qo.message_id,
            requiredRoles=qo.required_roles,
            confirmedParties=confirmed_parties,
        )
        self.session.add(session)
        await self.session.flush()
        await self.session.refresh(session)

        assert session.id is not None, "Session ID should not be None after flush"

        return ConfirmationSessionDto(
            id=session.id,
            status=session.status,
            canceler_id=session.cancelerId,
            confirmed_parties=session.confirmedParties or {},
            required_roles=session.requiredRoles,
        )

    async def update_confirmation_session_message_id(self, session_id: int, message_id: int):
        """
        更新确认会话的消息ID。
        """
        statement = (
            update(ConfirmationSession)
            .where(ConfirmationSession.id == session_id)  # type: ignore
            .values(messageId=message_id)
        )
        await self.session.exec(statement)  # type: ignore

    async def get_confirmation_session_by_message_id(
        self, message_id: int
    ) -> Optional[ConfirmationSession]:
        """
        根据消息ID获取确认会话。
        """
        statement = select(ConfirmationSession).where(ConfirmationSession.messageId == message_id)
        result = await self.session.exec(statement)
        return result.one_or_none()

    async def add_confirmation(
        self, session: ConfirmationSession, role: str, user_id: int
    ) -> ConfirmationSession:
        """
        向确认会话添加一个确认方。
        """
        # 确保 confirmedParties 是一个可修改的字典
        if session.confirmedParties is None:
            session.confirmedParties = {}

        # 创建副本以触发 SQLAlchemy 的变更检测
        new_confirmed_parties = session.confirmedParties.copy()
        new_confirmed_parties[role] = user_id
        session.confirmedParties = new_confirmed_parties

        # 检查是否所有角色都已确认
        if set(session.requiredRoles) == set(session.confirmedParties.keys()):
            session.status = 1  # 1: 已完成

        self.session.add(session)
        await self.session.flush()
        return session

    async def cancel_confirmation_session(
        self, session: ConfirmationSession, user_id: int
    ) -> ConfirmationSession:
        """
        取消一个确认会话。
        """
        session.status = 2  # 2: 已取消
        session.cancelerId = user_id
        self.session.add(session)
        await self.session.flush()
        return session

    async def abandon_proposal(self, qo: AbandonProposalQo) -> Proposal:
        """
        废弃一个提案。

        Args:
            qo: 包含废弃操作所需数据的查询对象。

        Returns:
            被更新的 Proposal 对象。

        Raises:
            ValueError: 如果找不到提案或提案状态不正确。
        """
        proposal = await self.get_proposal_by_thread_id(qo.thread_id)
        if not proposal:
            raise ValueError("未找到关连的提案。")
        if proposal.status != 1:  # 1: 执行中
            raise ValueError("只能废弃“执行中”的提案。")

        proposal.status = 3  # 3: 已废弃
        self.session.add(proposal)
        await self.session.flush()
        return proposal
