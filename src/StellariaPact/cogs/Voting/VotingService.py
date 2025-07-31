from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Voting.dto.VoteDetailDto import VoteDetailDto, VoterInfo
from StellariaPact.cogs.Voting.dto.VoteStatusDto import VoteStatusDto
from StellariaPact.cogs.Voting.qo.AdjustVoteTimeQo import AdjustVoteTimeQo
from StellariaPact.cogs.Voting.qo.GetVoteDetailsQo import GetVoteDetailsQo
from StellariaPact.cogs.Voting.qo.RecordVoteQo import RecordVoteQo
from StellariaPact.models.UserActivity import UserActivity
from StellariaPact.models.UserVote import UserVote
from StellariaPact.models.VoteSession import VoteSession


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

    async def create_vote_session(
        self, session: AsyncSession, thread_id: int
    ) -> VoteSession:
        """
        在指定的帖子中创建一个新的投票会话。
        如果已存在，则返回现有会话。
        """
        existing_session = await self.get_vote_session_by_thread_id(session, thread_id)
        if existing_session:
            return existing_session

        data = {"contextThreadId": thread_id}
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
            vote_record = UserVote(
                sessionId=vote_session.id, userId=qo.user_id, choice=qo.choice
            )

        session.add(vote_record)
        await session.commit()
        await session.refresh(vote_record)
        return vote_record

    async def get_expired_sessions(
        self, session: AsyncSession
    ) -> Sequence[VoteSession]:
        """
        获取所有已到期的投票会话。
        """
        now_utc = datetime.now(timezone.utc)
        statement = (
            select(VoteSession)
            .where(VoteSession.endTime != None)  # noqa: E711
            .where(VoteSession.status == 1)
            .where(VoteSession.endTime <= now_utc)  # type: ignore
        )
        result = await session.exec(statement)
        return result.all()

    async def tally_and_close_session(
        self, session: AsyncSession, vote_session: VoteSession
    ) -> VoteStatusDto:
        """
        计票并关闭一个投票会话。
        """
        statement = select(UserVote).where(UserVote.sessionId == vote_session.id)
        result = await session.exec(statement)
        all_votes = result.all()

        approve_votes = sum(1 for vote in all_votes if vote.choice == 1)
        reject_votes = sum(1 for vote in all_votes if vote.choice == 0)

        # 更新会话状态
        vote_session.status = 0
        session.add(vote_session)
        await session.commit()

        return VoteStatusDto(
            is_anonymous=vote_session.anonymousFlag,
            end_time=vote_session.endTime,
            status=vote_session.status,
            totalVotes=len(all_votes),
            approveVotes=approve_votes,
            rejectVotes=reject_votes,
        )

    async def update_user_activity(
        self, session: AsyncSession, user_id: int, thread_id: int
    ) -> UserActivity:
        """
        更新用户在特定帖子中的有效发言计数。
        """
        statement = select(UserActivity).where(
            UserActivity.userId == user_id,
            UserActivity.contextThreadId == thread_id,
        )
        result = await session.exec(statement)
        user_activity = result.one_or_none()

        if user_activity:
            user_activity.messageCount += 1
        else:
            data = {
                "userId": user_id,
                "contextThreadId": thread_id,
                "messageCount": 1,
            }
            user_activity = UserActivity.model_validate(data)

        session.add(user_activity)
        await session.commit()
        await session.refresh(user_activity)
        return user_activity

    async def adjust_vote_time(
        self, session: AsyncSession, qo: AdjustVoteTimeQo
    ) -> VoteSession:
        """
        调整投票的结束时间。
        """
        vote_session = await self.get_vote_session_by_thread_id(session, qo.thread_id)
        if not vote_session:
            raise ValueError("找不到指定的投票会话。")

        if vote_session.status == 0:
            raise ValueError("投票已经结束，无法调整时间。")

        # 如果当前没有结束时间，则以当前时间为基准
        base_time = vote_session.endTime or datetime.now(timezone.utc)
        new_end_time = base_time + timedelta(hours=qo.hours_to_adjust)

        vote_session.endTime = new_end_time
        session.add(vote_session)
        await session.commit()
        await session.refresh(vote_session)
        return vote_session

    async def get_vote_details(
        self, session: AsyncSession, qo: GetVoteDetailsQo
    ) -> VoteDetailDto:
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
            voters = [
                VoterInfo(user_id=vote.userId, choice=vote.choice)
                for vote in all_votes
            ]

        return VoteDetailDto(
            is_anonymous=vote_session.anonymousFlag,
            end_time=vote_session.endTime,
            status=vote_session.status,
            total_votes=len(all_votes),
            approve_votes=approve_votes,
            reject_votes=reject_votes,
            voters=voters,
        )
