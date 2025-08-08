import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import discord
from sqlalchemy.orm import selectinload
from sqlmodel import select

from StellariaPact.cogs.Voting.dto.VoteDetailDto import (VoteDetailDto,
                                                         VoterInfo)
from StellariaPact.cogs.Voting.dto.VotingChoicePanelDto import \
    VotingChoicePanelDto
from StellariaPact.cogs.Voting.qo.DeleteVoteQo import DeleteVoteQo
from StellariaPact.models.UserVote import UserVote
from StellariaPact.models.VoteSession import VoteSession

from ....share.StellariaPactBot import StellariaPactBot
from ....share.UnitOfWork import UnitOfWork
from ...Moderation.dto.ObjectionDetailsDto import ObjectionDetailsDto
from ..EligibilityService import EligibilityService
from ..qo.CreateVoteSessionQo import CreateVoteSessionQo
from ..qo.GetVoteDetailsQo import GetVoteDetailsQo
from ..qo.RecordVoteQo import RecordVoteQo
from ..qo.UpdateUserActivityQo import UpdateUserActivityQo
from ..views.ObjectionFormalVoteView import ObjectionFormalVoteView
from ..views.ObjectionVoteEmbedBuilder import ObjectionVoteEmbedBuilder

logger = logging.getLogger(__name__)


class VotingLogic:
    """
    处理与投票相关的业务逻辑。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot

    async def create_objection_vote_panel(
        self, thread: discord.Thread, objection_dto: ObjectionDetailsDto
    ):
        """
        在异议帖中创建专用的裁决投票面板。
        """
        # 计算结束时间
        # 默认投票时长为 48 小时
        end_time = datetime.now(timezone.utc) + timedelta(hours=48)

        # 构建 UI
        view = ObjectionFormalVoteView(self.bot)
        embed = ObjectionVoteEmbedBuilder.create_formal_embed(
            objection_dto=objection_dto, end_time=end_time
        )

        # 发送消息
        message = await self.bot.api_scheduler.submit(
            thread.send(embed=embed, view=view), priority=2
        )

        # 在数据库中创建会话
        async with UnitOfWork(self.bot.db_handler) as uow:
            qo: CreateVoteSessionQo = CreateVoteSessionQo(
                thread_id=thread.id,
                objection_id=objection_dto.objection_id,
                context_message_id=message.id,
                realtime=False,
                anonymous=True,
                end_time=end_time,
            )
            await uow.voting.create_vote_session(qo)

        logger.info(
            f"已在异议帖 {thread.id} 中为异议 {objection_dto.objection_id} 创建了投票面板。"
        )

    async def record_vote_and_get_details(self, qo: RecordVoteQo) -> VoteDetailDto:
        """
        处理用户的投票动作，并返回更新后的投票详情。
        这个方法是原子的，它将投票记录、计票和结果获取合并在一个事务中。

        Args:
            qo: 记录投票的查询对象，包含 message_id, user_id, 和 choice。

        Returns:
            一个包含最新投票状态的 DTO。

        Raises:
            ValueError: 如果找不到指定的投票会话。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 获取 VoteSession 和所有关联的 UserVotes
            statement = (
                select(VoteSession)
                .where(VoteSession.contextMessageId == qo.message_id)
                .options(selectinload(VoteSession.userVotes))  # type: ignore
            )
            result = await uow.session.exec(statement)
            vote_session = result.one_or_none()

            if not vote_session:
                raise ValueError(f"找不到与消息 ID {qo.message_id} 关联的投票会话。")

            # 在内存中处理投票逻辑
            existing_vote = next(
                (vote for vote in vote_session.userVotes if vote.userId == qo.user_id),
                None,
            )

            if existing_vote:
                # 如果用户已经投过票，更新他们的选项
                existing_vote.choice = qo.choice
                uow.session.add(existing_vote)
            else:
                # 如果是新投票，创建一个新的 UserVote 记录
                if vote_session.id is None:
                    # 在正常流程中这不应该发生，因为会话是从数据库加载的
                    raise ValueError("无法为没有 ID 的会话记录投票。")
                new_vote = UserVote(
                    sessionId=vote_session.id, userId=qo.user_id, choice=qo.choice
                )
                uow.session.add(new_vote)
                # 将新投票添加到内存列表以进行即时计票
                vote_session.userVotes.append(new_vote)

            # 在内存中计票
            all_votes = vote_session.userVotes
            approve_votes = sum(1 for vote in all_votes if vote.choice == 1)
            reject_votes = sum(1 for vote in all_votes if vote.choice == 0)

            voters = []
            if not vote_session.anonymousFlag:
                voters = [
                    VoterInfo(user_id=vote.userId, choice=vote.choice)
                    for vote in all_votes
                ]
            
            # 构建并返回 DTO
            return VoteDetailDto(
                is_anonymous=vote_session.anonymousFlag,
                realtime_flag=vote_session.realtimeFlag,
                end_time=vote_session.endTime,
                context_message_id=vote_session.contextMessageId,
                status=vote_session.status,
                total_votes=len(all_votes),
                approve_votes=approve_votes,
                reject_votes=reject_votes,
                voters=voters,
            )

    async def get_vote_details(self, qo: GetVoteDetailsQo) -> VoteDetailDto:
        """
        获取指定投票的当前状态和详细信息。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 获取 VoteSession 和所有关联的 UserVotes
            statement = (
                select(VoteSession)
                .where(VoteSession.contextMessageId == qo.message_id)
                .options(selectinload(VoteSession.userVotes))  # type: ignore
            )
            result = await uow.session.exec(statement)
            vote_session = result.one_or_none()

            if not vote_session:
                raise ValueError(f"找不到与消息 ID {qo.message_id} 关联的投票会话。")

            # 在内存中计票
            all_votes = vote_session.userVotes
            approve_votes = sum(1 for vote in all_votes if vote.choice == 1)
            reject_votes = sum(1 for vote in all_votes if vote.choice == 0)

            voters = []
            if not vote_session.anonymousFlag:
                voters = [
                    VoterInfo(user_id=vote.userId, choice=vote.choice)
                    for vote in all_votes
                ]

            # 构建并返回 DTO
            return VoteDetailDto(
                is_anonymous=vote_session.anonymousFlag,
                realtime_flag=vote_session.realtimeFlag,
                end_time=vote_session.endTime,
                context_message_id=vote_session.contextMessageId,
                status=vote_session.status,
                total_votes=len(all_votes),
                approve_votes=approve_votes,
                reject_votes=reject_votes,
                voters=voters,
            )

    async def get_vote_flags(self, message_id: int) -> tuple[bool, bool]:
        """
        以轻量级方式仅获取投票会话的匿名和实时标志。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            statement = select(
                VoteSession.anonymousFlag, VoteSession.realtimeFlag
            ).where(VoteSession.contextMessageId == message_id)
            result = await uow.session.exec(statement)
            flags = result.one_or_none()
            if not flags:
                raise ValueError(f"找不到与消息 ID {message_id} 关联的投票会话。")
            return flags[0], flags[1]  # (is_anonymous, is_realtime)

    async def toggle_anonymous(self, message_id: int) -> VoteDetailDto:
        """切换指定投票的匿名状态。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            vote_session = await uow.voting.get_vote_session_by_context_message_id(
                message_id
            )
            if not vote_session:
                raise ValueError(f"找不到与消息 ID {message_id} 关联的投票会话。")

            vote_session.anonymousFlag = not vote_session.anonymousFlag
            await uow.commit()
            return await self.get_vote_details(GetVoteDetailsQo(message_id=message_id))

    async def toggle_realtime(self, message_id: int) -> VoteDetailDto:
        """切换指定投票的实时票数状态。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            vote_session = await uow.voting.get_vote_session_by_context_message_id(
                message_id
            )
            if not vote_session:
                raise ValueError(f"找不到与消息 ID {message_id} 关联的投票会话。")

            vote_session.realtimeFlag = not vote_session.realtimeFlag
            await uow.commit()
            return await self.get_vote_details(GetVoteDetailsQo(message_id=message_id))

    async def delete_vote_and_get_details(self, qo: DeleteVoteQo) -> VoteDetailDto:
        """
        处理用户的弃权动作，并返回更新后的投票详情。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 获取 VoteSession 和所有关联的 UserVotes
            statement = (
                select(VoteSession)
                .where(VoteSession.contextMessageId == qo.message_id)
                .options(selectinload(VoteSession.userVotes))  # type: ignore
            )
            result = await uow.session.exec(statement)
            vote_session = result.one_or_none()

            if not vote_session:
                raise ValueError(f"找不到与消息 ID {qo.message_id} 关联的投票会话。")

            # 在内存中找到并删除用户的投票
            user_vote_to_delete = next(
                (vote for vote in vote_session.userVotes if vote.userId == qo.user_id),
                None,
            )
            
            if user_vote_to_delete:
                # 从数据库会话中标记删除
                await uow.session.delete(user_vote_to_delete)
                # 从内存集合中移除，以确保后续计数正确
                vote_session.userVotes.remove(user_vote_to_delete)

            # 在内存中重新计算投票统计
            all_votes = vote_session.userVotes
            approve_votes = sum(1 for vote in all_votes if vote.choice == 1)
            reject_votes = sum(1 for vote in all_votes if vote.choice == 0)

            voters = []
            if not vote_session.anonymousFlag:
                voters = [
                    VoterInfo(user_id=vote.userId, choice=vote.choice)
                    for vote in all_votes
                ]

            # 在提交事务之前构建 DTO，以避免在会话关闭后访问延迟加载的属性
            dto_to_return = VoteDetailDto(
                is_anonymous=vote_session.anonymousFlag,
                realtime_flag=vote_session.realtimeFlag,
                end_time=vote_session.endTime,
                context_message_id=vote_session.contextMessageId,
                status=vote_session.status,
                total_votes=len(all_votes),
                approve_votes=approve_votes,
                reject_votes=reject_votes,
                voters=voters,
            )

            return dto_to_return

    async def prepare_voting_choice_data(
        self, user_id: int, thread_id: int, message_id: int
    ) -> VotingChoicePanelDto:
        """
        准备投票选择视图所需的所有数据。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 并行获取所有需要的数据
            user_activity_task = uow.voting.check_user_eligibility(user_id, thread_id)
            vote_session_task = uow.voting.get_vote_session_by_context_message_id(
                message_id
            )
            user_activity, vote_session = await asyncio.gather(
                user_activity_task, vote_session_task
            )

            user_vote = None
            if vote_session and vote_session.id:
                user_vote = await uow.voting.get_user_vote_by_session_id(
                    user_id, vote_session.id
                )

            message_count = user_activity.messageCount if user_activity else 0
            is_eligible = EligibilityService.is_eligible(user_activity)
            is_validation_revoked = (
                user_activity.validation is False if user_activity else False
            )
            is_vote_active = vote_session.status == 1 if vote_session else False
            current_vote_choice = user_vote.choice if user_vote else None

            return VotingChoicePanelDto(
                is_eligible=is_eligible,
                is_vote_active=is_vote_active,
                message_count=message_count,
                current_vote_choice=current_vote_choice,
                is_validation_revoked=is_validation_revoked,
            )

    async def handle_message_creation(self, qo: UpdateUserActivityQo) -> None:
        """处理消息创建事件，增加用户活跃度。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            await uow.voting.update_user_activity(qo)

    async def handle_message_deletion(
        self, qo: UpdateUserActivityQo
    ) -> Optional[List[VoteDetailDto]]:
        """
        处理消息删除事件。
        - 减少用户活跃度。
        - 如果用户资格失效，则撤销其在该帖子下的所有投票。
        - 如果有投票被撤销，则返回所有需要更新的投票面板的详情。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            user_activity = await uow.voting.update_user_activity(qo)

            if EligibilityService.is_eligible(user_activity):
                return None

            # 尝试删除用户在该帖子中的所有投票
            deleted_count = await uow.voting.delete_all_user_votes_in_thread(
                user_id=qo.user_id, thread_id=qo.thread_id
            )

            if deleted_count == 0:
                return None

            # 获取所有会话及其关联的、更新后的投票
            statement = (
                select(VoteSession)
                .where(VoteSession.contextThreadId == qo.thread_id)
                .options(selectinload(VoteSession.userVotes)) #type: ignore
            )
            result = await uow.session.exec(statement)
            all_sessions_in_thread = result.all()

            # 在内存中为每个会话构建 DTO
            details_to_update = []
            for session in all_sessions_in_thread:
                if not session.contextMessageId:
                    continue

                all_votes = session.userVotes
                approve_votes = sum(1 for vote in all_votes if vote.choice == 1)
                reject_votes = sum(1 for vote in all_votes if vote.choice == 0)

                voters = []
                if not session.anonymousFlag:
                    voters = [
                        VoterInfo(user_id=vote.userId, choice=vote.choice)
                        for vote in all_votes
                    ]

                details_to_update.append(
                    VoteDetailDto(
                        is_anonymous=session.anonymousFlag,
                        realtime_flag=session.realtimeFlag,
                        end_time=session.endTime,
                        context_message_id=session.contextMessageId,
                        status=session.status,
                        total_votes=len(all_votes),
                        approve_votes=approve_votes,
                        reject_votes=reject_votes,
                        voters=voters,
                    )
                )
            return details_to_update
