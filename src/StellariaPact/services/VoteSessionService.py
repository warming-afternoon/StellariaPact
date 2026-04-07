import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence

from sqlalchemy import and_, update
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.cogs.Voting.dto import AdjustVoteTimeDto, OptionResult, VoteDetailDto, VoterInfo
from StellariaPact.cogs.Voting.qo import AdjustVoteTimeQo, CreateVoteSessionQo
from StellariaPact.dto import VoteSessionDto
from StellariaPact.models.Objection import Objection
from StellariaPact.models.Proposal import Proposal
from StellariaPact.models.UserVote import UserVote
from StellariaPact.models.VoteMessageMirror import VoteMessageMirror
from StellariaPact.models.VoteOption import VoteOption
from StellariaPact.models.VoteSession import VoteSession
from StellariaPact.share.enums import VoteSessionType

logger = logging.getLogger(__name__)


class VoteSessionService:
    """
    提供处理投票会话 (`VoteSession`) 相关数据库操作的服务。
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def update_vote_session_message_id(self, session_id: int, message_id: int):
        """
        更新投票会话的消息ID
        """
        statement = (
            update(VoteSession)
            .where(VoteSession.id == session_id)  # type: ignore
            .values(context_message_id=message_id)
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
            .values(voting_channel_message_id=message_id)
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
            select(VoteSession).where(VoteSession.context_message_id == message_id)
        )
        return result.one_or_none()

    async def get_vote_session_by_voting_channel_message_id(
        self, message_id: int
    ) -> Optional[VoteSession]:
        """
        根据投票频道消息ID获取投票会话
        """
        result = await self.session.exec(
            select(VoteSession).where(VoteSession.voting_channel_message_id == message_id)
        )
        return result.one_or_none()

    async def get_details_by_voting_channel_message_id(
        self, message_id: int
    ) -> Optional[VoteSession]:
        """根据主投票频道消息ID获取投票会话，并预加载投票详情"""
        statement = (
            select(VoteSession)
            .where(VoteSession.voting_channel_message_id == message_id)
            .options(selectinload(VoteSession.userVotes))  # type: ignore
        )
        return (await self.session.exec(statement)).one_or_none()

    async def get_details_by_mirror_message_id(
        self, message_id: int
    ) -> Optional[VoteSession]:
        """根据额外镜像的消息ID获取投票会话，并预加载投票详情"""
        statement = (
            select(VoteSession)
            .join(VoteMessageMirror, and_(VoteSession.id == VoteMessageMirror.session_id))  # type: ignore
            .where(VoteMessageMirror.message_id == message_id)
            .options(selectinload(VoteSession.userVotes))  # type: ignore
        )
        return (await self.session.exec(statement)).one_or_none()

    async def get_vote_session_with_details(self, message_id: int) -> Optional[VoteSession]:
        """
        根据消息ID获取投票会话，并预加载所有关联的 UserVotes
        """
        statement = (
            select(VoteSession)
            .where(VoteSession.context_message_id == message_id)
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
            .where(VoteSession.context_thread_id == thread_id)
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
            guild_id=qo.guild_id,
            context_thread_id=qo.thread_id,
            objection_id=qo.objection_id,
            proposal_id=qo.proposal_id,
            intake_id=qo.intake_id,
            context_message_id=qo.context_message_id,
            realtime_flag=qo.realtime,
            anonymous_flag=qo.anonymous,
            notify_flag=qo.notify_flag,
            end_time=qo.end_time,
            total_choices=qo.total_choices,
            session_type=qo.session_type,
            max_choices_per_user=qo.max_choices_per_user,
            ui_style=qo.ui_style,
        )
        self.session.add(new_session)
        await self.session.flush()
        await self.session.refresh(new_session)
        return VoteSessionDto.model_validate(new_session)

    async def update_vote_session_total_choices(self, session_id: int, total_choices: int):
        """更新投票会话的选项总数"""
        statement = (
            update(VoteSession)
            .where(VoteSession.id == session_id)  # type: ignore
            .values(total_choices=total_choices)  # type: ignore
            .returning(VoteSession.id)  # type: ignore
        )
        await self.session.exec(statement)

    async def get_vote_sessions_by_intake_id(self, intake_id: int) -> Sequence[VoteSession]:
        """根据草案 ID 获取支持收集阶段的投票会话。"""
        statement = (
            select(VoteSession)
            .where(VoteSession.intake_id == intake_id)
            .where(VoteSession.session_type == VoteSessionType.INTAKE_SUPPORT)
        )
        result = await self.session.exec(statement)
        sessions = result.all()
        return sessions

    async def get_expired_sessions(self) -> Sequence[VoteSessionDto]:
        """
        获取所有已到期的投票会话 (暂时仅获取1-普通投票)。
        """
        # TODO: 后续可以根据需要扩展到其他类型的投票
        now_utc = datetime.now(timezone.utc)
        statement = (
            select(VoteSession)
            .where(VoteSession.end_time != None)  # noqa: E711
            .where(VoteSession.status == 1)  # 1 表示 "进行中"
            .where(VoteSession.session_type == 1)  # 1-"普通投票"
            .where(VoteSession.end_time <= now_utc)  # type: ignore
        )
        result = await self.session.exec(statement)
        sessions = result.all()
        return [VoteSessionDto.model_validate(s) for s in sessions]

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
        statement = select(VoteSession).where(VoteSession.context_message_id == qo.message_id)
        result = await self.session.exec(statement)
        vote_session = result.one_or_none()

        if not vote_session:
            raise ValueError("找不到指定的投票会话。")

        if vote_session.status == 0:
            raise ValueError("投票已经结束，无法调整时间。")

        # 如果当前没有结束时间，则以当前时间为基准
        base_time = vote_session.end_time or datetime.now(timezone.utc)
        if base_time.tzinfo is None:
            base_time = base_time.replace(tzinfo=timezone.utc)

        old_end_time = base_time
        new_end_time = old_end_time + timedelta(hours=qo.hours_to_adjust)

        vote_session.end_time = new_end_time
        await self.session.flush()

        return AdjustVoteTimeDto(
            vote_session=VoteSessionDto.model_validate(vote_session),
            old_end_time=old_end_time,
        )

    async def toggle_anonymous(self, message_id: int) -> Optional[VoteSession]:
        """切换投票的匿名状态。"""
        vote_session = await self.get_vote_session_with_details(message_id)
        if not vote_session:
            return None

        vote_session.anonymous_flag = not vote_session.anonymous_flag
        self.session.add(vote_session)
        return vote_session

    async def toggle_realtime(self, message_id: int) -> Optional[VoteSession]:
        """切换投票的实时进度状态"""
        vote_session = await self.get_vote_session_with_details(message_id)
        if not vote_session:
            return None

        vote_session.realtime_flag = not vote_session.realtime_flag
        self.session.add(vote_session)
        return vote_session

    async def toggle_notify(self, message_id: int) -> Optional[VoteSession]:
        """切换投票的结束通知状态。"""
        vote_session = await self.get_vote_session_with_details(message_id)
        if not vote_session:
            return None
        vote_session.notify_flag = not vote_session.notify_flag
        self.session.add(vote_session)
        return vote_session

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
        vote_session.end_time = new_end_time

        self.session.add(vote_session)
        await self.session.flush()

        # 刷新以确保关联数据正确
        await self.session.refresh(vote_session)
        return vote_session

    @staticmethod
    def get_vote_details_dto(
        vote_session: VoteSession, vote_options: Sequence[VoteOption] | None = None
    ) -> VoteDetailDto:
        """
        根据给定的 VoteSession 对象（包含预加载的 userVotes）构建 VoteDetailDto。
        支持按类型分类选项：普通选项和异议选项。
        """
        all_votes: List[UserVote] = vote_session.userVotes
        option_results: List[OptionResult] = []
        normal_options: List[OptionResult] = []
        objection_options: List[OptionResult] = []
        vote_session_model: VoteSession = vote_session

        total_approve_votes = 0
        total_reject_votes = 0

        if vote_session_model.total_choices > 0 and vote_options:  # type: ignore
            for option in vote_options:
                option_model: VoteOption = option
                approve = sum(
                    1
                    for v in all_votes
                    if v.option_type == option_model.option_type
                    and v.choice_index == option_model.choice_index
                    and v.choice == 1  # type: ignore
                )
                reject = sum(
                    1
                    for v in all_votes
                    if v.option_type == option_model.option_type
                    and v.choice_index == option_model.choice_index
                    and v.choice == 0  # type: ignore
                )

                option_result = OptionResult(
                    option_id=option_model.id,
                    creator_id=option_model.creator_id,
                    choice_index=option_model.choice_index,  # type: ignore
                    choice_text=option_model.choice_text,  # type: ignore
                    approve_votes=approve,
                    reject_votes=reject,
                    total_votes=approve + reject,
                )

                option_results.append(option_result)

                # 按类型分类
                if option_model.option_type == 0:  # 普通选项
                    normal_options.append(option_result)
                else:  # 异议选项
                    objection_options.append(option_result)

                total_approve_votes += approve
                total_reject_votes += reject
        else:
            total_approve_votes = sum(1 for v in all_votes if v.choice == 1)
            total_reject_votes = sum(1 for v in all_votes if v.choice == 0)

        voters: List[VoterInfo] = []
        if not vote_session_model.anonymous_flag:
            voters = [
                VoterInfo(
                    user_id=v.user_id,
                    choice=v.choice,
                    choice_index=v.choice_index,  # type: ignore
                    option_type=v.option_type,  # type: ignore
                )
                for v in all_votes
            ]

        return VoteDetailDto(
            guild_id=vote_session_model.guild_id,
            context_thread_id=vote_session_model.context_thread_id,
            objection_id=vote_session_model.objection_id,
            voting_channel_message_id=getattr(
                vote_session_model, "voting_channel_message_id", None
            ),
            is_anonymous=vote_session_model.anonymous_flag,
            realtime_flag=vote_session_model.realtime_flag,
            notify_flag=vote_session_model.notify_flag,
            end_time=vote_session_model.end_time,
            context_message_id=vote_session_model.context_message_id,
            status=vote_session_model.status,
            total_choices=vote_session_model.total_choices,  # type: ignore
            total_approve_votes=total_approve_votes,
            total_reject_votes=total_reject_votes,
            total_votes=total_approve_votes + total_reject_votes,
            options=option_results,
            normal_options=normal_options,
            objection_options=objection_options,
            voters=voters,
            max_choices_per_user=getattr(vote_session_model, "max_choices_per_user", 999999),
            ui_style=getattr(vote_session_model, "ui_style", 1),
        )

    async def get_proposal_thread_id_by_objection_id(self, objection_id: int) -> Optional[int]:
        """
        通过异议ID查找关联提案的讨论帖ID。
        用于在异议投票中继承原提案的发言数。
        """
        statement = (
            select(Proposal.discussion_thread_id)
            .join(Objection, Objection.proposal_id == Proposal.id)  # type: ignore
            .where(Objection.id == objection_id)
        )
        result = await self.session.exec(statement)
        return result.one_or_none()

    async def add_mirror_message(
        self, session_id: int, guild_id: int, channel_id: int, message_id: int
    ):
        """
        添加一个额外的投票面板镜像记录
        """
        mirror = VoteMessageMirror(
            session_id=session_id,
            guild_id=guild_id,
            channel_id=channel_id,
            message_id=message_id
        )
        self.session.add(mirror)
        await self.session.flush()

    async def get_mirrors_by_session_id(self, session_id: int) -> Sequence[VoteMessageMirror]:
        """
        获取一个投票会话关联的所有额外镜像
        """
        statement = select(VoteMessageMirror).where(VoteMessageMirror.session_id == session_id)
        return (await self.session.exec(statement)).all()

    async def get_vote_session_by_mirror_message_id(
        self, message_id: int
    ) -> Optional[VoteSession]:
        """
        根据额外镜像的消息ID反查关联的原始投票会话
        由于没有实体外键，这里使用显式的相等条件进行关联查询。
        """

        statement = (
            select(VoteSession)
            .join(VoteMessageMirror, and_(VoteSession.id == VoteMessageMirror.session_id))  # type: ignore
            .where(VoteMessageMirror.message_id == message_id)
        )
        return (await self.session.exec(statement)).one_or_none()
