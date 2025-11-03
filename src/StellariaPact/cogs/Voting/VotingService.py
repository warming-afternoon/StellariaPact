import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlalchemy import func, update
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Voting.dto.AdjustVoteTimeDto import AdjustVoteTimeDto
from StellariaPact.cogs.Voting.dto.UserActivityDto import UserActivityDto
from StellariaPact.cogs.Voting.dto.UserVoteDto import UserVoteDto
from StellariaPact.cogs.Voting.dto.VoteDetailDto import VoteDetailDto, VoterInfo
from StellariaPact.cogs.Voting.dto.VoteSessionDto import VoteSessionDto
from StellariaPact.cogs.Voting.dto.VoteStatusDto import VoteStatusDto
from StellariaPact.cogs.Voting.qo.AdjustVoteTimeQo import AdjustVoteTimeQo
from StellariaPact.cogs.Voting.qo.CreateVoteSessionQo import CreateVoteSessionQo
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

    async def get_all_vote_sessions_by_thread_id(self, thread_id: int) -> Sequence[VoteSessionDto]:
        """根据帖子ID获取所有投票会话。"""
        statement = select(VoteSession).where(VoteSession.contextThreadId == thread_id)
        result = await self.session.exec(statement)
        sessions = result.all()
        return [VoteSessionDto.model_validate(s) for s in sessions]

    async def update_vote_session_message_id(self, session_id: int, message_id: int):
        """
        更新投票会话的消息ID
        """
        statement = (
            update(VoteSession)
            .where(VoteSession.id == session_id)  # type: ignore
            .values(contextMessageId=message_id)
            .returning(VoteSession.id)  # type: ignore
        )
        await self.session.exec(statement)

    async def update_voting_channel_message_id(self, session_id: int, message_id: int):
        """
        更新投票会话在投票频道中的消息ID。
        """
        statement = (
            update(VoteSession)
            .where(VoteSession.id == session_id)  # type: ignore
            .values(votingChannelMessageId=message_id)
            .returning(VoteSession.id)  # type: ignore
        )
        await self.session.exec(statement)

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

    async def get_vote_session_by_voting_channel_message_id(
        self, message_id: int
    ) -> Optional[VoteSession]:
        """
        根据投票频道消息ID获取投票会话
        """
        result = await self.session.exec(
            select(VoteSession).where(VoteSession.votingChannelMessageId == message_id)
        )
        return result.one_or_none()

    async def get_vote_session_with_details(self, message_id: int) -> Optional[VoteSession]:
        """
        根据消息ID获取投票会话，并预加载所有关联的 UserVotes
        """
        statement = (
            select(VoteSession)
            .where(VoteSession.contextMessageId == message_id)
            .options(selectinload(VoteSession.userVotes))  # type: ignore
        )
        result = await self.session.exec(statement)
        return result.one_or_none()

    async def get_all_sessions_in_thread_with_details(
        self, thread_id: int
    ) -> Sequence[VoteSession]:
        """
        获取帖子内所有的投票会话，并预加载每个会话的投票详情
        """
        statement = (
            select(VoteSession)
            .where(VoteSession.contextThreadId == thread_id)
            .options(selectinload(VoteSession.userVotes))  # type: ignore
        )
        result = await self.session.exec(statement)
        return result.all()

    async def create_vote_session(self, qo: CreateVoteSessionQo) -> VoteSessionDto:
        """
        在指定的上下文中创建一个新的投票会话
        """
        logger.debug(
            f"尝试创建投票会话，参数: thread_id={qo.thread_id}, message_id={qo.context_message_id}"
        )

        new_session = VoteSession(
            contextThreadId=qo.thread_id,
            objectionId=qo.objection_id,
            contextMessageId=qo.context_message_id,
            realtimeFlag=qo.realtime,
            anonymousFlag=qo.anonymous,
            notifyFlag=qo.notifyFlag,
            endTime=qo.end_time,
        )
        self.session.add(new_session)
        await self.session.flush()
        return VoteSessionDto.model_validate(new_session)

    async def record_vote(self, qo: RecordVoteQo) -> VoteSession:
        """
        记录或更新用户的投票。
        """
        vote_session = await self.get_vote_session_with_details(qo.message_id)
        if not vote_session:
            raise ValueError(f"找不到与消息 ID {qo.message_id} 关联的投票会话。")

        existing_vote = next(
            (vote for vote in vote_session.userVotes if vote.userId == qo.user_id),
            None,
        )

        if existing_vote:
            existing_vote.choice = qo.choice
            self.session.add(existing_vote)
        else:
            if vote_session.id is None:
                raise ValueError("无法为没有 ID 的会话记录投票。")
            new_vote = UserVote(sessionId=vote_session.id, userId=qo.user_id, choice=qo.choice)
            self.session.add(new_vote)
            vote_session.userVotes.append(new_vote)

        return vote_session

    async def delete_vote(self, user_id: int, message_id: int) -> Optional[VoteSession]:
        """
        删除用户的投票。
        """
        vote_session = await self.get_vote_session_with_details(message_id)
        if not vote_session:
            return None

        user_vote_to_delete = next(
            (vote for vote in vote_session.userVotes if vote.userId == user_id),
            None,
        )

        if user_vote_to_delete:
            await self.session.delete(user_vote_to_delete)
            vote_session.userVotes.remove(user_vote_to_delete)

        return vote_session

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
        根据会话ID获取用户的投票记录
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
        根据消息ID删除用户的投票记录
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
            UserVote.userId == user_id,
            UserVote.sessionId.in_(session_ids),  # type: ignore
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
            notify_flag=vote_session.notifyFlag,
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
        logger.info(f"尝试调整投票时间: message_id={qo.message_id}, hours={qo.hours_to_adjust}")
        statement = select(VoteSession).where(VoteSession.contextMessageId == qo.message_id)
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

    async def toggle_anonymous(self, message_id: int) -> Optional[VoteSession]:
        """切换投票的匿名状态。"""
        vote_session = await self.get_vote_session_with_details(message_id)
        if not vote_session:
            return None

        vote_session.anonymousFlag = not vote_session.anonymousFlag
        self.session.add(vote_session)
        return vote_session

    async def toggle_realtime(self, message_id: int) -> Optional[VoteSession]:
        """切换投票的实时进度状态"""
        vote_session = await self.get_vote_session_with_details(message_id)
        if not vote_session:
            return None

        vote_session.realtimeFlag = not vote_session.realtimeFlag
        self.session.add(vote_session)
        return vote_session

    async def toggle_notify(self, message_id: int) -> Optional[VoteSession]:
        """切换投票的结束通知状态。"""
        vote_session = await self.get_vote_session_with_details(message_id)
        if not vote_session:
            return None
        vote_session.notifyFlag = not vote_session.notifyFlag
        self.session.add(vote_session)
        return vote_session

    async def get_vote_flags(self, message_id: int) -> Optional[tuple[bool, bool, bool]]:
        """以轻量级方式仅获取投票会话的匿名、实时和通知标志。"""
        statement = select(
            VoteSession.anonymousFlag, VoteSession.realtimeFlag, VoteSession.notifyFlag
        ).where(VoteSession.contextMessageId == message_id)
        result = await self.session.exec(statement)
        flags = result.one_or_none()
        if not flags:
            return None
        return flags[0], flags[1], flags[2]

    async def reopen_vote_session(
        self, message_id: int, new_end_time: datetime
    ) -> Optional[VoteSession]:
        """
        重新开启一个已结束的投票会话。
        保留所有投票记录，只更新状态和结束时间。
        """
        vote_session = await self.get_vote_session_with_details(message_id)
        if not vote_session:
            raise ValueError(f"找不到与消息 ID {message_id} 关联的投票会话。")

        if vote_session.status == 1:
            raise ValueError("投票仍在进行中，无法重新开启。请使用“调整时间”功能。")

        # 更新状态和结束时间
        vote_session.status = 1  # 1-进行中
        vote_session.endTime = new_end_time

        self.session.add(vote_session)
        await self.session.flush()

        # 刷新以确保关联数据正确
        await self.session.refresh(vote_session)
        return vote_session

    @staticmethod
    def get_vote_details_dto(vote_session: VoteSession) -> VoteDetailDto:
        """
        根据给定的 VoteSession 对象（包含预加载的 userVotes）构建 VoteDetailDto。
        """
        all_votes = vote_session.userVotes
        approve_votes = sum(1 for vote in all_votes if vote.choice == 1)
        reject_votes = sum(1 for vote in all_votes if vote.choice == 0)

        voters = []
        if not vote_session.anonymousFlag:
            voters = [VoterInfo(user_id=vote.userId, choice=vote.choice) for vote in all_votes]

        return VoteDetailDto(
            context_thread_id=vote_session.contextThreadId,
            objection_id=vote_session.objectionId,
            voting_channel_message_id=getattr(vote_session, "votingChannelMessageId", None),
            is_anonymous=vote_session.anonymousFlag,
            realtime_flag=vote_session.realtimeFlag,
            notify_flag=vote_session.notifyFlag,
            end_time=vote_session.endTime,
            context_message_id=vote_session.contextMessageId,
            status=vote_session.status,
            total_votes=len(all_votes),
            approve_votes=approve_votes,
            reject_votes=reject_votes,
            voters=voters,
        )
