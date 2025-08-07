import logging
from typing import Optional, Sequence

from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Moderation.dto.ConfirmationSessionDto import \
    ConfirmationSessionDto
from StellariaPact.cogs.Moderation.dto.HandleSupportObjectionResultDto import \
    HandleSupportObjectionResultDto
from StellariaPact.cogs.Moderation.dto.ObjectionCreationResultDto import \
    ObjectionCreationResultDto
from StellariaPact.cogs.Moderation.dto.ObjectionDetailsDto import \
    ObjectionDetailsDto
from StellariaPact.cogs.Moderation.qo.AbandonProposalQo import \
    AbandonProposalQo
from StellariaPact.cogs.Moderation.qo.CreateConfirmationSessionQo import \
    CreateConfirmationSessionQo
from StellariaPact.cogs.Moderation.qo.CreateObjectionAndVoteSessionShellQo import \
    CreateObjectionAndVoteSessionShellQo
from StellariaPact.cogs.Moderation.qo.ObjectionSupportQo import \
    ObjectionSupportQo
from StellariaPact.models.ConfirmationSession import ConfirmationSession
from StellariaPact.models.Objection import Objection
from StellariaPact.models.Proposal import Proposal
from StellariaPact.models.UserActivity import UserActivity
from StellariaPact.models.UserVote import UserVote
from StellariaPact.models.VoteSession import VoteSession
from StellariaPact.share.enums.ConfirmationStatus import ConfirmationStatus
from StellariaPact.share.enums.ProposalStatus import ProposalStatus

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

    async def create_proposal(self, thread_id: int, proposer_id: int, title: str) -> None:
        """
        尝试创建一个新的提案，如果因唯一性约束而失败，则静默处理。

        Args:
            thread_id: 提案讨论帖的ID。
            proposer_id: 提案发起人的ID。
            title: 提案的标题。
        """
        new_proposal = Proposal(
            discussionThreadId=thread_id,
            proposerId=proposer_id,
            title=title,
            status=ProposalStatus.DISCUSSION,
        )
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

    async def get_objections_by_proposal_id(self, proposal_id: int) -> Sequence[Objection]:
        """
        根据提案ID获取所有相关的异议。
        """
        statement = (
            select(Objection)
            .where(Objection.proposalId == proposal_id)
            .order_by(Objection.createdAt.asc())  # type: ignore
        )
        result = await self.session.exec(statement)
        return result.all()

    async def get_objection_by_id(self, objection_id: int) -> Optional[Objection]:
        """
        根据ID获取异议。
        """
        return await self.session.get(Objection, objection_id)

    async def get_objection_by_review_thread_id(
        self, review_thread_id: int
    ) -> Optional[Objection]:
        """
        根据审核帖子ID获取异议。
        """
        statement = select(Objection).where(Objection.reviewThreadId == review_thread_id)
        result = await self.session.exec(statement)
        return result.one_or_none()

    async def update_objection_reason(
        self, objection_id: int, new_reason: str, user_id: int
    ) -> Objection:
        """
        更新异议的理由，并进行权限检查。
        """
        objection = await self.get_objection_by_id(objection_id)
        if not objection:
            raise ValueError(f"未找到ID为 {objection_id} 的异议。")

        if objection.objectorId != user_id:
            raise PermissionError("只有异议发起人才能修改理由。")

        objection.reason = new_reason
        self.session.add(objection)
        await self.session.flush()
        await self.session.refresh(objection)
        return objection

    async def get_objection_by_thread_id(self, thread_id: int) -> Optional[ObjectionDetailsDto]:
        """
        根据异议帖子ID获取异议的详细信息，包括其关联的提案。
        使用预加载（eager loading）来避免懒加载问题。
        """
        statement = (
            select(Objection)
            .where(Objection.objectionThreadId == thread_id)
            .options(selectinload(Objection.proposal))  # type: ignore
        )
        result = await self.session.exec(statement)
        objection = result.one_or_none()

        if not objection or not objection.proposal:
            return None

        # 向类型检查器断言 ID 的存在，因为它们是从数据库加载的
        assert objection.id is not None, "Objection ID should not be None"
        assert objection.proposal.id is not None, "Associated Proposal ID should not be None"

        # 将模型数据打包到 DTO 中，以实现层间解耦
        return ObjectionDetailsDto(
            objection_id=objection.id,
            objection_reason=objection.reason,
            objector_id=objection.objectorId,
            proposal_id=objection.proposal.id,
            proposal_title=objection.proposal.title,
        )

    async def create_objection_and_vote_session_shell(
        self, qo: CreateObjectionAndVoteSessionShellQo
    ) -> ObjectionCreationResultDto:
        """
        原子性地创建一个新的异议和一个关联的、但没有消息ID的“空壳”投票会话。
        这是两阶段提交的第一步。返回一个只包含ID的DTO。
        """
        # 创建异议
        new_objection = Objection(
            proposalId=qo.proposal_id,
            objector_id=qo.objector_id,
            reason=qo.reason,
            requiredVotes=qo.required_votes,
            status=qo.status,
        )
        self.session.add(new_objection)
        await self.session.flush()

        # 创建投票会话空壳
        assert new_objection.id is not None, "Objection ID is None after flush"
        new_vote_session = VoteSession(
            contextThreadId=qo.thread_id,
            objectionId=new_objection.id,
            contextMessageId=None,  # 设置为空，等待后续更新
            anonymousFlag=qo.is_anonymous,
            realtimeFlag=qo.is_realtime,
            endTime=qo.end_time,
        )
        self.session.add(new_vote_session)
        await self.session.flush()
        assert new_vote_session.id is not None, "VoteSession ID is None after flush"

        return ObjectionCreationResultDto(
            objection_id=new_objection.id, vote_session_id=new_vote_session.id
        )

    async def update_vote_session_message_id(self, session_id: int, message_id: int):
        """
        在一个独立的事务中更新投票会话的消息ID。
        这是两阶段提交的第二步。
        """
        statement = (
            update(VoteSession)
            .where(VoteSession.id == session_id)  # type: ignore
            .values(contextMessageId=message_id)
            .returning(VoteSession.id)  # type: ignore
        )
        await self.session.exec(statement)

    async def update_objection_status(self, objection_id: int, status: int) -> Optional[Objection]:
        """
        更新异议的状态。
        """
        objection = await self.get_objection_by_id(objection_id)
        if not objection:
            logger.warning(f"尝试更新状态时，未找到ID为 {objection_id} 的异议。")
            return None

        objection.status = status
        self.session.add(objection)
        await self.session.flush()
        await self.session.refresh(objection)
        logger.debug(f"已将异议 {objection_id} 的状态更新为 {status}。")
        return objection

    async def update_objection_thread_id(
        self, objection_id: int, objection_thread_id: int
    ) -> Optional[Objection]:
        """
        更新异议的讨论帖子ID。
        """
        objection = await self.get_objection_by_id(objection_id)
        if not objection:
            logger.warning(f"尝试更新异议帖子ID时，未找到ID为 {objection_id} 的异议。")
            return None

        objection.objectionThreadId = objection_thread_id
        self.session.add(objection)
        await self.session.flush()
        await self.session.refresh(objection)
        logger.debug(f"已将异议 {objection_id} 的帖子ID更新为 {objection_thread_id}。")
        return objection

    async def update_objection_review_thread_id(
        self, objection_id: int, review_thread_id: int
    ) -> Optional[Objection]:
        """
        更新异议的审核帖子ID。
        """
        objection = await self.get_objection_by_id(objection_id)
        if not objection:
            logger.warning(f"尝试更新审核帖子ID时，未找到ID为 {objection_id} 的异议。")
            return None

        objection.reviewThreadId = review_thread_id
        self.session.add(objection)
        await self.session.flush()
        await self.session.refresh(objection)
        logger.debug(f"已将异议 {objection_id} 的审核帖子ID更新为 {review_thread_id}。")
        return objection

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
            session.status = ConfirmationStatus.COMPLETED

        self.session.add(session)
        await self.session.flush()
        return session

    async def cancel_confirmation_session(
        self, session: ConfirmationSession, user_id: int
    ) -> ConfirmationSession:
        """
        取消一个确认会话。
        """
        session.status = ConfirmationStatus.CANCELED
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
        if proposal.status != ProposalStatus.EXECUTING:
            raise ValueError("只能废弃“执行中”的提案。")

        proposal.status = ProposalStatus.ABANDONED
        self.session.add(proposal)
        await self.session.flush()
        return proposal

    async def objection_support(self, qo: ObjectionSupportQo) -> HandleSupportObjectionResultDto:
        """
        原子性地处理对异议的支持或撤回操作

        此方法将所有数据库读写操作封装在单个事务中：
        1.  通过一次查询获取VoteSession及其关联的Objection和Proposal。
        2.  检查用户当前是否已投票。
        3.  根据用户的操作（'support' 或 'withdraw'）创建或删除投票记录。
        4.  获取最新的票数。
        5.  返回一个包含核心状态和Embed渲染数据的完整DTO。

        Args:
            qo: 包含用户ID、消息ID和操作类型的查询对象。

        Returns:
            一个DTO，包含了更新UI和后续逻辑判断所需的所有信息。

        Raises:
            ValueError: 如果找不到投票会话或关联的异议/提案。
        """
        # 1. 数据读取与验证（一次性预加载所有关联数据）
        vote_session_statement = (
            select(VoteSession)
            .where(VoteSession.contextMessageId == qo.messageId)
            .options(
                selectinload(VoteSession.objection).selectinload(Objection.proposal)  # type: ignore
            )
        )
        vote_session = (await self.session.exec(vote_session_statement)).one_or_none()

        if (
            not vote_session
            or not vote_session.id
            or not vote_session.objection
            or not vote_session.objection.proposal
        ):
            raise ValueError("错误：找不到对应的投票会话、关联的异议或提案。")

        objection = vote_session.objection
        proposal = vote_session.objection.proposal

        # 断言以确保类型安全
        assert objection.id is not None, "Objection ID cannot be None."
        assert proposal.id is not None, "Proposal ID cannot be None."

        # 2. 检查用户投票状态
        user_vote_statement = select(UserVote).where(
            UserVote.sessionId == vote_session.id, UserVote.userId == qo.userId
        )
        user_vote = (await self.session.exec(user_vote_statement)).one_or_none()

        user_has_voted = user_vote is not None
        user_action_result: str

        # 3. 根据动作执行写操作
        if qo.action == "support":
            if user_has_voted:
                user_action_result = "already_supported"
            else:
                new_vote = UserVote(sessionId=vote_session.id, userId=qo.userId, choice=1)
                self.session.add(new_vote)
                user_action_result = "supported"
        elif qo.action == "withdraw":
            if not user_has_voted:
                user_action_result = "not_supported"
            else:
                await self.session.delete(user_vote)  # type: ignore
                user_action_result = "withdrew"

        await self.session.flush()

        # 4. 获取最新票数
        count_statement = (
            select(func.count()).select_from(UserVote).where(UserVote.sessionId == vote_session.id)
        )
        current_supporters = (await self.session.exec(count_statement)).one()

        # 5. 组装并返回DTO
        return HandleSupportObjectionResultDto(
            current_supporters=current_supporters,
            required_supporters=objection.requiredVotes,
            is_goal_reached=(current_supporters >= objection.requiredVotes),
            is_vote_recorded=user_action_result in ["supported", "already_supported"],
            user_action_result=user_action_result,
            objection_status=objection.status,
            # --- 以下是渲染 Embed 所需的额外数据 ---
            objection_id=objection.id,
            proposal_id=proposal.id,
            proposal_title=proposal.title,
            proposal_discussion_thread_id=proposal.discussionThreadId,
            objector_id=objection.objectorId,
            objection_reason=objection.reason,
        )
