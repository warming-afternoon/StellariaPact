import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Voting.dto.AdjustVoteTimeDto import AdjustVoteTimeDto
from StellariaPact.cogs.Voting.dto.VoteDetailDto import VoteDetailDto, VoterInfo
from StellariaPact.cogs.Voting.dto.VoteStatusDto import VoteStatusDto
from StellariaPact.cogs.Voting.qo.AdjustVoteTimeQo import AdjustVoteTimeQo
from StellariaPact.cogs.Voting.qo.CreateVoteSessionQo import CreateVoteSessionQo
from StellariaPact.cogs.Voting.qo.GetVoteDetailsQo import GetVoteDetailsQo
from StellariaPact.cogs.Voting.qo.RecordVoteQo import RecordVoteQo
from StellariaPact.cogs.Voting.qo.UpdateUserActivityQo import UpdateUserActivityQo
from StellariaPact.models.UserActivity import UserActivity
from StellariaPact.models.UserVote import UserVote
from StellariaPact.models.VoteSession import VoteSession

logger = logging.getLogger(__name__)


class VotingService:
    """
    提供处理投票相关业务逻辑的服务。
    """

    async def get_vote_session_by_thread_id(
        self, session: AsyncSession, thread_id: int
    ) -> Optional[VoteSession]:
        """
        根据帖子ID获取投票会话。
        """
        result = await session.exec(
            select(VoteSession).where(VoteSession.contextThreadId == thread_id)
        )
        return result.one_or_none()

    async def get_vote_session_by_id(
        self, session: AsyncSession, session_id: int
    ) -> Optional[VoteSession]:
        """
        根据会话ID获取投票会话。
        """
        return await session.get(VoteSession, session_id)

    async def create_vote_session(
        self, session: AsyncSession, qo: CreateVoteSessionQo
    ) -> VoteSession:
        """
        在指定的帖子中创建一个新的投票会话。
        如果已存在，则返回现有会话。
        """
        existing_session = await self.get_vote_session_by_thread_id(session, qo.thread_id)
        if existing_session:
            return existing_session

        data = {
            "contextThreadId": qo.thread_id,
            "contextMessageId": qo.context_message_id,
            "realtimeFlag": qo.realtime,
            "anonymousFlag": qo.anonymous,
            "endTime": qo.end_time,
        }
        new_session = VoteSession.model_validate(data)
        session.add(new_session)
        await session.commit()
        await session.refresh(new_session)
        return new_session

    async def check_user_eligibility(
        self, session: AsyncSession, user_id: int, thread_id: int
    ) -> Optional[UserActivity]:
        """
        获取用户在特定帖子中的活动记录，用于判断投票资格。
        """
        statement = select(UserActivity).where(
            UserActivity.userId == user_id,
            UserActivity.contextThreadId == thread_id,
        )
        result = await session.exec(statement)
        return result.one_or_none()

    async def record_user_vote(
        self, session: AsyncSession, qo: RecordVoteQo
    ) -> Optional[UserVote]:
        """
        记录或更新用户的投票。
        """
        vote_session = await self.get_vote_session_by_thread_id(session, qo.thread_id)
        if not vote_session:
            return None

        statement = select(UserVote).where(
            UserVote.userId == qo.user_id, UserVote.sessionId == vote_session.id
        )
        result = await session.exec(statement)
        existing_vote = result.one_or_none()

        if existing_vote:
            existing_vote.choice = qo.choice
            vote_record = existing_vote
        else:
            if vote_session.id is None:
                # This should not happen in practice if the session is from the DB
                raise ValueError("Cannot record a vote for a session without an ID.")
            vote_record = UserVote(sessionId=vote_session.id, userId=qo.user_id, choice=qo.choice)

        session.add(vote_record)
        await session.commit()
        await session.refresh(vote_record)
        return vote_record

    async def get_user_vote(
        self, session: AsyncSession, user_id: int, thread_id: int
    ) -> Optional[UserVote]:
        """
        获取用户在特定投票会话中的投票记录。
        """
        vote_session = await self.get_vote_session_by_thread_id(session, thread_id)
        if not vote_session:
            return None

        statement = select(UserVote).where(
            UserVote.userId == user_id, UserVote.sessionId == vote_session.id
        )
        result = await session.exec(statement)
        return result.one_or_none()

    async def delete_user_vote(self, session: AsyncSession, user_id: int, thread_id: int) -> bool:
        """
        删除用户的投票记录 (弃票)。
        """
        vote_session = await self.get_vote_session_by_thread_id(session, thread_id)
        if not vote_session:
            return False

        statement = select(UserVote).where(
            UserVote.userId == user_id, UserVote.sessionId == vote_session.id
        )
        result = await session.exec(statement)
        existing_vote = result.one_or_none()

        if existing_vote:
            await session.delete(existing_vote)
            await session.commit()
            return True
        return False

    async def get_expired_sessions(self, session: AsyncSession) -> Sequence[VoteSession]:
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
        result = await session.exec(statement)
        return result.all()

    async def tally_and_close_session(
        self, session: AsyncSession, vote_session: VoteSession
    ) -> VoteStatusDto:
        """
        计票并关闭一个投票会话。
        传入的 vote_session 对象必须是与当前 session 关联的活动实例。
        """
        # 确保对象在当前会话中是“活动的”，如果不是，则合并它。
        # 这比重新查询更有效率。
        if vote_session not in session:
            vote_session = await session.merge(vote_session)

        statement = select(UserVote).where(UserVote.sessionId == vote_session.id)
        result = await session.exec(statement)
        all_votes = result.all()

        approve_votes = sum(1 for vote in all_votes if vote.choice == 1)
        reject_votes = sum(1 for vote in all_votes if vote.choice == 0)

        # 更新会话状态
        vote_session.status = 0  # 0: 已结束
        session.add(vote_session)
        await session.commit()
        await session.refresh(vote_session)

        return VoteStatusDto(
            is_anonymous=vote_session.anonymousFlag,
            realtime_flag=vote_session.realtimeFlag,
            end_time=vote_session.endTime,
            status=vote_session.status,
            totalVotes=len(all_votes),
            approveVotes=approve_votes,
            rejectVotes=reject_votes,
        )

    async def update_user_activity(
        self, session: AsyncSession, qo: UpdateUserActivityQo
    ) -> UserActivity:
        """
        更新用户在特定帖子中的有效发言计数。
        如果用户活动记录不存在，则会创建一个。
        """
        statement = select(UserActivity).where(
            UserActivity.userId == qo.user_id,
            UserActivity.contextThreadId == qo.thread_id,
        )
        result = await session.exec(statement)
        user_activity = result.one_or_none()

        if user_activity:
            # 确保计数不会变为负数
            new_count = user_activity.messageCount + qo.change
            user_activity.messageCount = max(0, new_count)
        else:
            # 如果是减少操作，但记录不存在，则无需创建
            if qo.change < 0:
                # 返回一个临时的、未保存的实例，表示没有变化
                return UserActivity(
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

        session.add(user_activity)
        await session.commit()
        await session.refresh(user_activity)
        return user_activity

    async def adjust_vote_time(
        self, session: AsyncSession, qo: AdjustVoteTimeQo
    ) -> AdjustVoteTimeDto:
        """
        调整投票的结束时间。

        Args:
            session: 数据库会话。
            qo: 调整时间的查询对象。

        Returns:
            一个包含操作结果的 DTO。

        Raises:
            ValueError: 如果找不到投票或投票已结束。
        """
        vote_session = await self.get_vote_session_by_thread_id(session, qo.thread_id)
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
        session.add(vote_session)
        await session.commit()
        await session.refresh(vote_session)

        return AdjustVoteTimeDto(vote_session=vote_session, old_end_time=old_end_time)

    async def toggle_anonymous(
        self, session: AsyncSession, thread_id: int
    ) -> Optional[VoteSession]:
        """切换投票的匿名状态。"""
        vote_session = await self.get_vote_session_by_thread_id(session, thread_id)
        if not vote_session:
            return None

        vote_session.anonymousFlag = not vote_session.anonymousFlag
        session.add(vote_session)
        await session.commit()
        await session.refresh(vote_session)
        return vote_session

    async def toggle_realtime(
        self, session: AsyncSession, thread_id: int
    ) -> Optional[VoteSession]:
        """切换投票的实时进度状态。"""
        vote_session = await self.get_vote_session_by_thread_id(session, thread_id)
        if not vote_session:
            return None

        vote_session.realtimeFlag = not vote_session.realtimeFlag
        session.add(vote_session)
        await session.commit()
        await session.refresh(vote_session)
        return vote_session

    async def get_vote_details(self, session: AsyncSession, qo: GetVoteDetailsQo) -> VoteDetailDto:
        """
        获取投票的详细状态，包括票数和投票者信息。
        """
        vote_session = await self.get_vote_session_by_thread_id(session, qo.thread_id)
        if not vote_session:
            raise ValueError("找不到指定的投票会话。")

        statement = select(UserVote).where(UserVote.sessionId == vote_session.id)
        result = await session.exec(statement)
        all_votes = result.all()

        approve_votes = sum(1 for vote in all_votes if vote.choice == 1)
        reject_votes = sum(1 for vote in all_votes if vote.choice == 0)

        voters = []
        if not vote_session.anonymousFlag:
            voters = [VoterInfo(user_id=vote.userId, choice=vote.choice) for vote in all_votes]

        return VoteDetailDto(
            is_anonymous=vote_session.anonymousFlag,
            realtime_flag=vote_session.realtimeFlag,
            end_time=vote_session.endTime,
            status=vote_session.status,
            total_votes=len(all_votes),
            approve_votes=approve_votes,
            reject_votes=reject_votes,
            voters=voters,
        )
