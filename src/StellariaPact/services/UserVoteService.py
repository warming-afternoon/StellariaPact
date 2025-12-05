from typing import Optional, Sequence

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Voting.qo.RecordVoteQo import RecordVoteQo
from StellariaPact.dto.UserVoteDto import UserVoteDto
from StellariaPact.models.UserVote import UserVote
from StellariaPact.models.VoteSession import VoteSession


class UserVoteService:
    """
    提供处理用户投票记录 (`UserVote`) 相关数据库操作的服务。
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_session_id(self, user_id: int, session_id: int) -> Optional[UserVoteDto]:
        """
        根据会话ID获取用户的投票记录
        """
        statement = select(UserVote).where(
            UserVote.user_id == user_id, UserVote.session_id == session_id
        )
        result = await self.session.exec(statement)
        vote = result.one_or_none()
        if not vote:
            return None
        return UserVoteDto.model_validate(vote)

    async def record_vote(self, qo: RecordVoteQo, vote_session: VoteSession) -> VoteSession:
        """
        记录或更新用户的投票。
        """
        if not vote_session:
            raise ValueError(f"找不到与消息 ID {qo.message_id} 关联的投票会话。")

        existing_vote = next(
            (
                vote
                for vote in vote_session.userVotes
                if vote.user_id == qo.user_id and vote.choice_index == qo.choice_index
            ),
            None,
        )

        if existing_vote:
            existing_vote.choice = qo.choice
            self.session.add(existing_vote)
        else:
            if vote_session.id is None:
                raise ValueError("无法为没有 ID 的会话记录投票。")
            new_vote = UserVote(
                session_id=vote_session.id,
                user_id=qo.user_id,
                choice=qo.choice,
                choice_index=qo.choice_index,
            )
            self.session.add(new_vote)
            vote_session.userVotes.append(new_vote)

        return vote_session

    async def delete_vote(
        self, user_id: int, choice_index: int, vote_session: VoteSession
    ) -> Optional[VoteSession]:
        """
        删除用户的投票。
        """
        if not vote_session:
            return None

        user_vote_to_delete = next(
            (
                vote
                for vote in vote_session.userVotes
                if vote.user_id == user_id and vote.choice_index == choice_index
            ),
            None,
        )

        if user_vote_to_delete:
            await self.session.delete(user_vote_to_delete)
            vote_session.userVotes.remove(user_vote_to_delete)

        return vote_session

    async def delete_all_user_votes_in_thread(
        self, user_id: int, session_ids: Sequence[int]
    ) -> int:
        """
        删除一个用户在指定投票会话中的所有投票。
        """
        if not session_ids:
            return 0

        # 找到用户在这些会话中的所有投票
        votes_statement = select(UserVote).where(
            UserVote.user_id == user_id,
            UserVote.session_id.in_(session_ids),  # type: ignore
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
            select(func.count(UserVote.id)).where(UserVote.session_id == session_id)  # type: ignore
        )
        count = result.one_or_none()
        return count if count is not None else 0
