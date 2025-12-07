import logging
from typing import Optional, Sequence

from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Moderation.dto.ObjectionCreationResultDto import ObjectionCreationResultDto
from StellariaPact.cogs.Moderation.qo.CreateObjectionAndVoteSessionShellQo import (
    CreateObjectionAndVoteSessionShellQo,
)
from StellariaPact.cogs.Moderation.qo.CreateObjectionQo import CreateObjectionQo
from StellariaPact.cogs.Moderation.qo.ObjectionSupportQo import ObjectionSupportQo
from StellariaPact.dto import HandleSupportObjectionResultDto, ObjectionDetailsDto
from StellariaPact.dto.ObjectionDto import ObjectionDto
from StellariaPact.models.Objection import Objection
from StellariaPact.models.UserVote import UserVote
from StellariaPact.models.VoteSession import VoteSession

logger = logging.getLogger(__name__)


class ObjectionService:
    """
    提供处理议事管理相关业务逻辑的服务。
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_objections_by_proposal_id(self, proposal_id: int) -> Sequence[Objection]:
        """
        根据提案ID获取所有相关的异议
        """
        statement = (
            select(Objection)
            .where(Objection.proposal_id == proposal_id)
            .order_by(Objection.created_at.asc())  # type: ignore
        )
        result = await self.session.exec(statement)
        return result.all()

    async def get_objection_by_id(self, objection_id: int) -> Optional[Objection]:
        """
        根据ID获取异议。
        """
        return await self.session.get(Objection, objection_id)

    async def get_objection_details_by_id(
        self, objection_id: int
    ) -> Optional[ObjectionDetailsDto]:
        """
        根据异议ID获取异议的详细信息，包括其关联的提案。
        """
        statement = (
            select(Objection)
            .where(Objection.id == objection_id)
            .options(selectinload(Objection.proposal))  # type: ignore
        )
        result = await self.session.exec(statement)
        objection = result.one_or_none()

        if not objection or not objection.proposal:
            return None

        # 向类型检查器断言 ID 的存在，因为它们是从数据库加载的
        assert objection.id is not None, "Objection ID should not be None"
        assert objection.proposal.id is not None, "Associated Proposal ID should not be None"

        return ObjectionDetailsDto(
            objection_id=objection.id,
            objection_reason=objection.reason,
            objector_id=objection.objector_id,
            proposal_id=objection.proposal.id,
            proposal_title=objection.proposal.title,
        )

    async def get_objection_by_review_thread_id(
        self, review_thread_id: int
    ) -> Optional[Objection]:
        """
        根据审核帖子ID获取异议。
        """
        statement = select(Objection).where(Objection.review_thread_id == review_thread_id)
        result = await self.session.exec(statement)
        return result.one_or_none()

    async def get_objection_by_thread_id(self, thread_id: int) -> Optional[ObjectionDetailsDto]:
        """
        根据异议帖子ID获取异议的详细信息，包括其关联的提案。
        """
        statement = (
            select(Objection)
            .where(Objection.objection_thread_id == thread_id)
            .options(selectinload(Objection.proposal))  # type: ignore
        )
        result = await self.session.exec(statement)
        objection = result.one_or_none()

        if not objection or not objection.proposal:
            return None

        # 向类型检查器断言 ID 的存在，因为它们是从数据库加载的
        assert objection.id is not None, "Objection ID should not be None"
        assert objection.proposal.id is not None, "Associated Proposal ID should not be None"

        # 将模型数据打包到 DTO 中
        return ObjectionDetailsDto(
            objection_id=objection.id,
            objection_reason=objection.reason,
            objector_id=objection.objector_id,
            proposal_id=objection.proposal.id,
            proposal_title=objection.proposal.title,
        )

    async def create_objection(self, qo: CreateObjectionQo) -> ObjectionDto:
        """
        创建一个新的异议，并返回其 DTO。
        """
        new_objection = Objection(
            proposal_id=qo.proposal_id,
            objector_id=qo.objector_id,
            reason=qo.reason,
            required_votes=qo.required_votes,
            status=qo.status,
        )
        self.session.add(new_objection)
        await self.session.flush()
        dto = ObjectionDto.model_validate(new_objection)
        return dto

    async def create_objection_and_vote_session_shell(
        self, qo: CreateObjectionAndVoteSessionShellQo
    ) -> ObjectionCreationResultDto:
        """
        原子性地创建一个新的异议和一个关联的、但没有消息ID的“空壳”投票会话。
        这是两阶段提交的第一步。返回一个只包含ID的DTO。
        """
        # 创建异议
        new_objection = Objection(
            proposal_id=qo.proposal_id,
            objector_id=qo.objector_id,
            reason=qo.reason,
            required_votes=qo.required_votes,
            status=qo.status,
        )
        self.session.add(new_objection)
        await self.session.flush()

        # 创建投票会话空壳
        assert new_objection.id is not None, "Objection ID is None after flush"
        new_vote_session = VoteSession(
            guild_id=qo.guild_id,
            context_thread_id=qo.thread_id,
            objection_id=new_objection.id,
            context_message_id=None,  # 设置为空，等待后续更新
            anonymous_flag=qo.is_anonymous,
            realtime_flag=qo.is_realtime,
            end_time=qo.end_time,
        )
        self.session.add(new_vote_session)
        await self.session.flush()
        assert new_vote_session.id is not None, "VoteSession ID is None after flush"

        return ObjectionCreationResultDto(
            objection_id=new_objection.id, vote_session_id=new_vote_session.id
        )

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

        objection.objection_thread_id = objection_thread_id
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

        objection.review_thread_id = review_thread_id
        self.session.add(objection)
        await self.session.flush()
        await self.session.refresh(objection)
        logger.debug(f"已将异议 {objection_id} 的审核帖子ID更新为 {review_thread_id}。")
        return objection

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
        # 数据读取与验证（一次性预加载所有关联数据）
        vote_session_statement = (
            select(VoteSession)
            .where(VoteSession.context_message_id == qo.message_id)
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

        # 检查用户投票状态
        user_vote_statement = select(UserVote).where(
            UserVote.session_id == vote_session.id, UserVote.user_id == qo.user_id
        )
        user_vote = (await self.session.exec(user_vote_statement)).one_or_none()

        user_has_voted = user_vote is not None
        user_action_result: str

        # 根据动作执行写操作
        if qo.action == "support":
            if user_has_voted:
                user_action_result = "already_supported"
            else:
                new_vote = UserVote(session_id=vote_session.id, user_id=qo.user_id, choice=1)
                self.session.add(new_vote)
                user_action_result = "supported"
        elif qo.action == "withdraw":
            if not user_has_voted:
                user_action_result = "not_supported"
            else:
                await self.session.delete(user_vote)  # type: ignore
                user_action_result = "withdrew"

        await self.session.flush()

        # 获取最新票数
        count_statement = (
            select(func.count())
            .select_from(UserVote)
            .where(UserVote.session_id == vote_session.id)
        )
        current_supporters = (await self.session.exec(count_statement)).one()

        # 组装并返回DTO
        return HandleSupportObjectionResultDto(
            current_supporters=current_supporters,
            required_supporters=objection.required_votes,
            is_goal_reached=(current_supporters >= objection.required_votes),
            is_vote_recorded=user_action_result in ["supported", "already_supported"],
            user_action_result=user_action_result,
            objection_status=objection.status,
            # --- 以下是渲染 Embed 所需的额外数据 ---
            objection_id=objection.id,
            proposal_id=proposal.id,
            proposal_title=proposal.title,
            proposal_discussion_thread_id=proposal.discussion_thread_id,
            objector_id=objection.objector_id,
            objection_reason=objection.reason,
        )
