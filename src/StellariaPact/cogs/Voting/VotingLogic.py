import asyncio
import logging
from datetime import datetime
from typing import List, Optional

import discord

from StellariaPact.cogs.Voting.dto.VoteDetailDto import VoteDetailDto
from StellariaPact.cogs.Voting.dto.VotingChoicePanelDto import \
    VotingChoicePanelDto
from StellariaPact.cogs.Voting.EligibilityService import EligibilityService
from StellariaPact.cogs.Voting.qo.AdjustVoteTimeQo import AdjustVoteTimeQo
from StellariaPact.cogs.Voting.qo.CreateVoteSessionQo import \
    CreateVoteSessionQo
from StellariaPact.cogs.Voting.qo.DeleteVoteQo import DeleteVoteQo
from StellariaPact.cogs.Voting.qo.RecordVoteQo import RecordVoteQo
from StellariaPact.cogs.Voting.qo.UpdateUserActivityQo import \
    UpdateUserActivityQo
from StellariaPact.cogs.Voting.VotingService import VotingService
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.TimeUtils import TimeUtils
from StellariaPact.share.UnitOfWork import UnitOfWork

logger = logging.getLogger(__name__)


class VotingLogic:
    """
    处理与投票相关的业务逻辑。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot

    async def update_vote_session_message_id(self, session_id: int, message_id: int):
        """
        更新投票会话的消息ID
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            await uow.voting.update_vote_session_message_id(session_id, message_id)
            await uow.commit()

    async def create_objection_vote_session(
        self,
        thread_id: int,
        objection_id: int,
        message_id: int,
        end_time: datetime,
    ) -> None:
        """
        在数据库中创建异议投票会话。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            qo = CreateVoteSessionQo(
                thread_id=thread_id,
                objection_id=objection_id,
                context_message_id=message_id,
                realtime=False,
                anonymous=True,
                end_time=end_time,
            )
            await uow.voting.create_vote_session(qo)

        logger.info(f"为异议 {objection_id} 在帖子 {thread_id} 中创建数据库投票会话。")

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
            updated_session = await uow.voting.record_vote(qo)
            return VotingService.get_vote_details_dto(updated_session)

    async def get_vote_details(self, message_id: int) -> VoteDetailDto:
        """
        获取指定投票的当前状态和详细信息。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            vote_session = await uow.voting.get_vote_session_with_details(message_id)
            if not vote_session:
                raise ValueError(f"找不到与消息 ID {message_id} 关联的投票会话。")
            return VotingService.get_vote_details_dto(vote_session)

    async def get_vote_flags(self, message_id: int) -> tuple[bool, bool]:
        """
        以轻量级方式仅获取投票会话的匿名和实时标志。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            flags = await uow.voting.get_vote_flags(message_id)
            if not flags:
                raise ValueError(f"找不到与消息 ID {message_id} 关联的投票会话。")
            return flags  # (is_anonymous, is_realtime)

    async def toggle_anonymous(self, message_id: int) -> VoteDetailDto:
        """切换指定投票的匿名状态。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            updated_session = await uow.voting.toggle_anonymous(message_id)
            if not updated_session:
                raise ValueError(f"找不到与消息 ID {message_id} 关联的投票会话。")
            await uow.commit()
            # 重新获取以加载 userVotes
            final_session = await uow.voting.get_vote_session_with_details(message_id)
            if not final_session:
                raise ValueError(f"在切换匿名状态后无法重新获取会话 {message_id}。")
            return VotingService.get_vote_details_dto(final_session)

    async def toggle_realtime(self, message_id: int) -> VoteDetailDto:
        """切换指定投票的实时票数状态。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            updated_session = await uow.voting.toggle_realtime(message_id)
            if not updated_session:
                raise ValueError(f"找不到与消息 ID {message_id} 关联的投票会话。")
            await uow.commit()
            # 重新获取以加载 userVotes
            final_session = await uow.voting.get_vote_session_with_details(message_id)
            if not final_session:
                raise ValueError(f"在切换实时状态后无法重新获取会话 {message_id}。")
            return VotingService.get_vote_details_dto(final_session)

    async def delete_vote_and_get_details(self, qo: DeleteVoteQo) -> VoteDetailDto:
        """
        处理用户的弃权动作，并返回更新后的投票详情。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            updated_session = await uow.voting.delete_vote(
                user_id=qo.user_id, message_id=qo.message_id
            )
            if not updated_session:
                raise ValueError(f"找不到与消息 ID {qo.message_id} 关联的投票会话。")
            return VotingService.get_vote_details_dto(updated_session)

    async def prepare_voting_choice_data(
        self, user_id: int, thread_id: int, message_id: int
    ) -> VotingChoicePanelDto:
        """
        准备投票选择视图所需的所有数据。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 并行获取所有需要的数据
            user_activity_task = uow.voting.check_user_eligibility(user_id, thread_id)
            vote_session_task = uow.voting.get_vote_session_by_context_message_id(message_id)
            user_activity, vote_session = await asyncio.gather(
                user_activity_task, vote_session_task
            )

            user_vote = None
            if vote_session and vote_session.id:
                user_vote = await uow.voting.get_user_vote_by_session_id(user_id, vote_session.id)

            message_count = user_activity.messageCount if user_activity else 0
            is_eligible = EligibilityService.is_eligible(user_activity)
            is_validation_revoked = user_activity.validation is False if user_activity else False
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
            all_sessions_in_thread = await uow.voting.get_all_sessions_in_thread_with_details(
                qo.thread_id
            )

            # 在内存中为每个会话构建 DTO
            details_to_update = [
                VotingService.get_vote_details_dto(session)
                for session in all_sessions_in_thread
                if session.contextMessageId
            ]
            return details_to_update

    async def reopen_vote(
        self,
        thread_id: int,
        message_id: int,
        hours_to_add: int,
        operator: discord.User | discord.Member,
    ):
        """
        处理重新开启投票的业务流程，并分派事件以更新UI。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 获取当前会话以记录旧的结束时间
            current_session = await uow.voting.get_vote_session_by_context_message_id(message_id)
            if not current_session or not current_session.endTime:
                raise RuntimeError(f"无法为消息 {message_id} 找到投票会话或其结束时间。")
            old_end_time = current_session.endTime

            target_tz = self.bot.config.get("timezone", "UTC")
            new_end_time = TimeUtils.get_utc_end_time(
                duration_hours=hours_to_add, target_tz=target_tz
            )

            reopened_session = await uow.voting.reopen_vote_session(message_id, new_end_time)
            if not reopened_session:
                raise RuntimeError("更新数据库失败。")

            await uow.commit()

            final_session = await uow.voting.get_vote_session_with_details(message_id)
            if not final_session:
                raise RuntimeError("重新获取会话失败。")

            vote_details = VotingService.get_vote_details_dto(final_session)
            self.bot.dispatch(
                "vote_settings_changed",
                thread_id,
                message_id,
                vote_details,
                operator,
                f"已将此投票重新开启，将额外持续 **{hours_to_add}** 小时。",
                new_end_time,
                old_end_time,
            )

    async def adjust_vote_time(
        self, thread_id: int, hours_to_adjust: int, operator: discord.User | discord.Member
    ):
        """
        处理调整投票时间的业务流程，并分派事件以更新UI。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            qo = AdjustVoteTimeQo(thread_id=thread_id, hours_to_adjust=hours_to_adjust)
            result_dto = await uow.voting.adjust_vote_time(qo)
            await uow.commit()

            message_id = result_dto.vote_session.contextMessageId
            if not message_id:
                raise ValueError("找不到关联的消息ID。")

            final_session = await uow.voting.get_vote_session_with_details(message_id)
            if not final_session:
                raise RuntimeError("重新获取会话失败。")

            vote_details = VotingService.get_vote_details_dto(final_session)

            change_text = (
                f"延长了 **{hours_to_adjust}** 小时"
                if hours_to_adjust > 0
                else f"缩短了 **{-hours_to_adjust}** 小时"
            )

            self.bot.dispatch(
                "vote_settings_changed",
                thread_id,
                message_id,
                vote_details,
                operator,
                f"调整了投票时间，{change_text}。",
                result_dto.vote_session.endTime,
                result_dto.old_end_time,
            )
