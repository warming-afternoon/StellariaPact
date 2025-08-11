import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Voting.dto.AdjustVoteTimeDto import AdjustVoteTimeDto
from StellariaPact.cogs.Voting.dto.UserActivityDto import UserActivityDto
from StellariaPact.cogs.Voting.dto.UserVoteDto import UserVoteDto
from StellariaPact.cogs.Voting.dto.VoteSessionDto import VoteSessionDto
from StellariaPact.cogs.Voting.dto.VoteStatusDto import VoteStatusDto
from StellariaPact.cogs.Voting.qo.AdjustVoteTimeQo import AdjustVoteTimeQo
from StellariaPact.cogs.Voting.qo.CreateVoteSessionQo import \
    CreateVoteSessionQo
from StellariaPact.cogs.Voting.qo.UpdateUserActivityQo import \
    UpdateUserActivityQo
from StellariaPact.models.UserActivity import UserActivity
from StellariaPact.models.UserVote import UserVote
from StellariaPact.models.VoteSession import VoteSession

logger = logging.getLogger(__name__)


class VotingService:
    """
    提供处理投票相关业务逻辑的服务。
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_vote_session_by_thread_id(self, thread_id: int) -> Optional[VoteSessionDto]:
        """
        根据帖子ID获取投票会话。
        """
        statement = select(VoteSession).where(VoteSession.contextThreadId == thread_id)
        result = await self.session.exec(statement)
        session = result.one_or_none()
        if not session:
            return None
        return VoteSessionDto.model_validate(session)

    async def get_all_vote_sessions_by_thread_id(
        self, thread_id: int
    ) -> Sequence[VoteSessionDto]:
        """根据帖子ID获取所有投票会话。"""
        statement = select(VoteSession).where(VoteSession.contextThreadId == thread_id)
        result = await self.session.exec(statement)
        sessions = result.all()
        return [VoteSessionDto.model_validate(s) for s in sessions]

    async def get_vote_session_by_context_message_id(
        self, message_id: int
    ) -> Optional[VoteSession]:
        """
        根据上下文消息ID获取投票会话。
        """
        result = await self.session.exec(
            select(VoteSession).where(VoteSession.contextMessageId == message_id)
        )
        return result.one_or_none()

    async def create_vote_session(self, qo: CreateVoteSessionQo) -> VoteSessionDto:
        """
        在指定的上下文中创建一个新的投票会话。
        如果已存在，则返回现有会话。
        """

        filters = []
        if qo.thread_id:
            filters.append(VoteSession.contextThreadId == qo.thread_id)
        if qo.objection_id:
            filters.append(VoteSession.objectionId == qo.objection_id)
        if qo.context_message_id:
            filters.append(VoteSession.contextMessageId == qo.context_message_id)

        statement = select(VoteSession).where(*filters)
        result = await self.session.exec(statement)
        existing_session = result.one_or_none()
        if existing_session:
            return VoteSessionDto.model_validate(existing_session)

        # 如果没有找到现有会话，则创建新的会话
        data = {
            "contextThreadId": qo.thread_id,
            "objectionId": qo.objection_id,
            "contextMessageId": qo.context_message_id,
            "realtimeFlag": qo.realtime,
            "anonymousFlag": qo.anonymous,
            "endTime": qo.end_time,
        }
        new_session = VoteSession.model_validate(data)
        self.session.add(new_session)
        await self.session.flush()
        return VoteSessionDto.model_validate(new_session)

    async def check_user_eligibility(
        self, user_id: int, thread_id: int
    ) -> Optional[UserActivityDto]:
        """
        获取用户在特定帖子中的活动记录，用于判断投票资格。
        """
        statement = select(UserActivity).where(
            UserActivity.userId == user_id,
            UserActivity.contextThreadId == thread_id,
        )
        result = await self.session.exec(statement)
        activity = result.one_or_none()
        if not activity:
            return None
        return UserActivityDto.model_validate(activity)

    async def get_user_vote_by_session_id(
        self, user_id: int, session_id: int
    ) -> Optional[UserVoteDto]:
        """
        根据会话ID获取用户的投票记录。
        """
        statement = select(UserVote).where(
            UserVote.userId == user_id, UserVote.sessionId == session_id
        )
        result = await self.session.exec(statement)
        vote = result.one_or_none()
        if not vote:
            return None
        return UserVoteDto.model_validate(vote)

    async def delete_user_vote_by_message_id(self, user_id: int, message_id: int) -> bool:
        """
        根据消息ID删除用户的投票记录。
        """
        vote_session = await self.get_vote_session_by_context_message_id(message_id)
        if not vote_session or not vote_session.id:
            return False

        statement = select(UserVote).where(
            UserVote.userId == user_id, UserVote.sessionId == vote_session.id
        )
        result = await self.session.exec(statement)
        existing_vote = result.one_or_none()

        if existing_vote:
            await self.session.delete(existing_vote)
            return True
        return False

    async def delete_all_user_votes_in_thread(self, user_id: int, thread_id: int) -> int:
        """
        删除一个用户在特定帖子内所有投票会话中的所有投票。

        Args:
            user_id: 用户的ID。
            thread_id: 帖子的ID。

        Returns:
            被成功删除的投票记录数量。
        """
        # 找到该帖子下的所有投票会话 ID
        session_ids_statement = select(VoteSession.id).where(
            VoteSession.contextThreadId == thread_id
        )
        session_ids_result = await self.session.exec(session_ids_statement)
        session_ids = session_ids_result.all()

        if not session_ids:
            return 0

        # 找到用户在这些会话中的所有投票
        votes_statement = select(UserVote).where(
            UserVote.userId == user_id, UserVote.sessionId.in_(session_ids)  # type: ignore
        )
        votes_result = await self.session.exec(votes_statement)
        votes_to_delete = votes_result.all()

        if not votes_to_delete:
            return 0

        # 删除所有找到的投票
        for vote in votes_to_delete:
            await self.session.delete(vote)

        return len(votes_to_delete)

    async def get_vote_count_by_session_id(self, session_id: int) -> int:
        """
        获取特定投票会话的总票数
        """
        result = await self.session.exec(
            select(func.count(UserVote.id)).where(UserVote.sessionId == session_id)  # type: ignore
        )
        count = result.one_or_none()
        return count if count is not None else 0

    async def get_expired_sessions(self) -> Sequence[VoteSessionDto]:
        """
        获取所有已到期的投票会话。
        """
        now_utc = datetime.now(timezone.utc)
        statement = (
            select(VoteSession)
            .where(VoteSession.endTime != None)  # noqa: E711
            .where(VoteSession.status == 1)  # 1 表示 "进行中"
            .where(VoteSession.endTime <= now_utc)  # type: ignore
        )
        result = await self.session.exec(statement)
        sessions = result.all()
        return [VoteSessionDto.model_validate(s) for s in sessions]

    async def tally_and_close_session(self, vote_session_id: int) -> VoteStatusDto:
        """
        计票并关闭一个投票会话。
        """
        # 使用 selectinload 一次性加载投票会话及其所有关联的投票记录
        statement = (
            select(VoteSession)
            .where(VoteSession.id == vote_session_id)
            .options(selectinload(VoteSession.userVotes))  # type: ignore
        )
        result = await self.session.exec(statement)
        vote_session = result.one_or_none()

        if not vote_session:
            raise ValueError(f"找不到ID为 {vote_session_id} 的投票会话")

        # 从已加载的关系中获取投票
        all_votes = vote_session.userVotes

        approve_votes = sum(1 for vote in all_votes if vote.choice == 1)
        reject_votes = sum(1 for vote in all_votes if vote.choice == 0)

        # 更新会话状态
        vote_session.status = 0  # 已结束
        await self.session.flush()

        voters_dto_list = (
            [UserVoteDto.model_validate(vote) for vote in all_votes]
            if not vote_session.anonymousFlag
            else []
        )

        return VoteStatusDto(
            is_anonymous=vote_session.anonymousFlag,
            realtime_flag=vote_session.realtimeFlag,
            end_time=vote_session.endTime,
            status=vote_session.status,
            totalVotes=len(all_votes),
            approveVotes=approve_votes,
            rejectVotes=reject_votes,
            voters=voters_dto_list,
        )

    async def update_user_activity(self, qo: UpdateUserActivityQo) -> UserActivityDto:
        """
        更新用户在特定帖子中的有效发言计数。
        如果用户活动记录不存在，则会创建一个。
        """
        statement = select(UserActivity).where(
            UserActivity.userId == qo.user_id,
            UserActivity.contextThreadId == qo.thread_id,
        )
        result = await self.session.exec(statement)
        user_activity = result.one_or_none()

        if user_activity:
            # 确保计数不会变为负数
            new_count = user_activity.messageCount + qo.change
            user_activity.messageCount = max(0, new_count)
        else:
            # 如果是减少操作，但记录不存在，则无需创建
            if qo.change < 0:
                # 返回一个临时的、未保存的实例，表示没有变化
                return UserActivityDto(
                    id=-1,  # Placeholder ID
                    userId=qo.user_id,
                    contextThreadId=qo.thread_id,
                    messageCount=0,
                    validation=True,
                )
            # 仅在增加时创建新记录
            user_activity = UserActivity(
                userId=qo.user_id,
                contextThreadId=qo.thread_id,
                messageCount=1,
            )

        self.session.add(user_activity)
        await self.session.flush()
        return UserActivityDto.model_validate(user_activity)

    async def adjust_vote_time(self, qo: AdjustVoteTimeQo) -> AdjustVoteTimeDto:
        """
        调整投票的结束时间。

        Args:
            qo: 调整时间的查询对象。

        Returns:
            一个包含操作结果的 DTO。

        Raises:
            ValueError: 如果找不到投票或投票已结束。
        """
        statement = select(VoteSession).where(VoteSession.contextThreadId == qo.thread_id)
        result = await self.session.exec(statement)
        vote_session = result.one_or_none()
        if not vote_session:
            raise ValueError("找不到指定的投票会话。")

        if vote_session.status == 0:
            raise ValueError("投票已经结束，无法调整时间。")

        # 如果当前没有结束时间，则以当前时间为基准
        # 确保基础时间是时区感知的 (UTC)
        base_time = vote_session.endTime or datetime.now(timezone.utc)
        if base_time.tzinfo is None:
            base_time = base_time.replace(tzinfo=timezone.utc)

        old_end_time = base_time
        new_end_time = old_end_time + timedelta(hours=qo.hours_to_adjust)

        vote_session.endTime = new_end_time
        await self.session.flush()

        return AdjustVoteTimeDto(
            vote_session=VoteSessionDto.model_validate(vote_session), old_end_time=old_end_time
        )

    async def toggle_anonymous(self, thread_id: int) -> Optional[VoteSessionDto]:
        """切换投票的匿名状态。"""
        statement = select(VoteSession).where(VoteSession.contextThreadId == thread_id)
        result = await self.session.exec(statement)
        vote_session = result.one_or_none()
        if not vote_session:
            return None

        vote_session.anonymousFlag = not vote_session.anonymousFlag
        await self.session.flush()
        return VoteSessionDto.model_validate(vote_session)

    async def toggle_realtime(self, thread_id: int) -> Optional[VoteSessionDto]:
        """切换投票的实时进度状态。"""
        statement = select(VoteSession).where(VoteSession.contextThreadId == thread_id)
        result = await self.session.exec(statement)
        vote_session = result.one_or_none()
        if not vote_session:
            return None

        vote_session.realtimeFlag = not vote_session.realtimeFlag
        await self.session.flush()
        return VoteSessionDto.model_validate(vote_session)

