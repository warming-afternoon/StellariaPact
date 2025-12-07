import asyncio
import logging
from typing import List, Optional

import discord

from StellariaPact.cogs.Voting import EligibilityService
from StellariaPact.cogs.Voting.dto import (
    OptionResult,
    VoteDetailDto,
    VoteStatusDto,
    VotingChoicePanelDto,
)
from StellariaPact.cogs.Voting.qo import (
    AdjustVoteTimeQo,
    DeleteVoteQo,
    RecordVoteQo,
    UpdateUserActivityQo,
)
from StellariaPact.dto import UserActivityDto, UserVoteDto, VoteSessionDto
from StellariaPact.models.VoteSession import VoteSession
from StellariaPact.services.VoteSessionService import VoteSessionService
from StellariaPact.share import StellariaPactBot, TimeUtils, UnitOfWork

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
            await uow.vote_session.update_vote_session_message_id(session_id, message_id)
            await uow.commit()

    async def record_vote_and_get_details(self, qo: RecordVoteQo) -> VoteDetailDto:
        """
        处理用户的投票动作，并返回更新后的投票详情。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 先获取会话，以便知道是否需要检查父帖子
            vote_session = await uow.vote_session.get_vote_session_with_details(qo.message_id)
            if not vote_session:
                raise ValueError(f"找不到与消息 ID {qo.message_id} 关联的投票会话。")

            # 检查资格
            is_eligible, _, _ = await self._get_combined_eligibility_data(
                uow, qo.user_id, qo.thread_id, vote_session
            )

            if not is_eligible:
                raise PermissionError("投票资格已失效（有效发言数不足或已被撤销资格）。")

            # 记录投票
            updated_session = await uow.user_vote.record_vote(qo, vote_session)

            vote_options = None
            if updated_session.id:
                vote_options = await uow.vote_option.get_vote_options(updated_session.id)
            return VoteSessionService.get_vote_details_dto(updated_session, vote_options)

    async def get_vote_details(self, message_id: int) -> VoteDetailDto:
        """
        获取指定投票的当前状态和详细信息。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            vote_session = await uow.vote_session.get_vote_session_with_details(message_id)
            if not vote_session:
                raise ValueError(f"找不到与消息 ID {message_id} 关联的投票会话。")

            vote_options = None
            if vote_session.id:
                vote_options = await uow.vote_option.get_vote_options(vote_session.id)
            return VoteSessionService.get_vote_details_dto(vote_session, vote_options)

    async def get_vote_flags(self, message_id: int) -> tuple[bool, bool, bool]:
        """以轻量级方式仅获取投票会话的匿名、实时和通知标志。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            flags = await uow.vote_session.get_vote_flags(message_id)
            if not flags:
                raise ValueError(f"找不到与消息 ID {message_id} 关联的投票会话。")
            return flags  # (is_anonymous, is_realtime, is_notify)

    async def _get_combined_eligibility_data(
        self, uow: UnitOfWork, user_id: int, thread_id: int, vote_session: VoteSession
    ) -> tuple[bool, int, bool]:
        """
        内部辅助方法：获取当前上下文和可能的父上下文的用户活动，并返回 eligibility 状态。

        Args:
            uow: UnitOfWork 实例，用于数据库操作。
            user_id: 需要检查资格的用户 ID。
            thread_id: 当前帖子的 ID。
            vote_session: 当前的投票会话对象，用于检查是否存在关联的父帖子。

        Returns:
            一个元组 (is_eligible, total_message_count, is_validation_revoked)，包含：
            - is_eligible (bool): 用户是否拥有投票资格。
            - total_message_count (int): 用户在当前帖子和父帖子中的总有效发言数。
            - is_validation_revoked (bool): 用户的投票资格是否因管理员操作而被明确撤销。
        """
        # 准备任务列表
        tasks = []

        # 获取当前帖子活动
        tasks.append(uow.user_activity.get_user_activity(user_id, thread_id))

        # (可选): 获取继承帖子活动
        parent_thread_id = None
        if vote_session and vote_session.objection_id:
            parent_thread_id = await uow.vote_session.get_proposal_thread_id_by_objection_id(
                vote_session.objection_id
            )
            if parent_thread_id:
                tasks.append(uow.user_activity.get_user_activity(user_id, parent_thread_id))

        # 并行执行查询
        results = await asyncio.gather(*tasks)

        current_activity_orm = results[0]
        inherited_activity_orm = results[1] if parent_thread_id and len(results) > 1 else None

        # 在会话内转换为 DTO
        current_activity_dto = (
            UserActivityDto.model_validate(current_activity_orm) if current_activity_orm else None
        )
        inherited_activity_dto = (
            UserActivityDto.model_validate(inherited_activity_orm)
            if inherited_activity_orm
            else None
        )

        # 计算资格
        is_eligible = EligibilityService.is_eligible(current_activity_dto, inherited_activity_dto)

        # 计算显示用的总发言数
        total_message_count = (
            current_activity_dto.message_count if current_activity_dto else 0
        ) + (inherited_activity_dto.message_count if inherited_activity_dto else 0)

        # 获取当前验证状态 (如果当前没记录，默认为有效，除非已被禁言会产生记录)
        is_validation_revoked = False
        if current_activity_dto and not current_activity_dto.validation:
            is_validation_revoked = True

        return is_eligible, total_message_count, is_validation_revoked

    async def toggle_anonymous(self, message_id: int) -> VoteDetailDto:
        """切换指定投票的匿名状态。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            updated_session = await uow.vote_session.toggle_anonymous(message_id)
            if not updated_session:
                raise ValueError(f"找不到与消息 ID {message_id} 关联的投票会话。")
            await uow.commit()
            # 重新获取以加载 userVotes
            final_session = await uow.vote_session.get_vote_session_with_details(message_id)
            if not final_session:
                raise ValueError(f"在切换匿名状态后无法重新获取会话 {message_id}。")
            return VoteSessionService.get_vote_details_dto(final_session)

    async def toggle_realtime(self, message_id: int) -> VoteDetailDto:
        """切换指定投票的实时票数状态。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            updated_session = await uow.vote_session.toggle_realtime(message_id)
            if not updated_session:
                raise ValueError(f"找不到与消息 ID {message_id} 关联的投票会话。")
            await uow.commit()
            # 重新获取以加载 userVotes
            final_session = await uow.vote_session.get_vote_session_with_details(message_id)
            if not final_session:
                raise ValueError(f"在切换实时状态后无法重新获取会话 {message_id}。")
            return VoteSessionService.get_vote_details_dto(final_session)

    async def toggle_notify(self, message_id: int) -> VoteDetailDto:
        """切换指定投票的结束通知状态。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            updated_session = await uow.vote_session.toggle_notify(message_id)
            if not updated_session:
                raise ValueError(f"找不到与消息 ID {message_id} 关联的投票会话。")
            await uow.commit()
            # 重新获取以加载 userVotes
            final_session = await uow.vote_session.get_vote_session_with_details(message_id)
            if not final_session:
                raise ValueError(f"在切换通知状态后无法重新获取会话 {message_id}。")
            return VoteSessionService.get_vote_details_dto(final_session)

    async def delete_vote_and_get_details(self, qo: DeleteVoteQo) -> VoteDetailDto:
        """
        处理用户的弃权动作，并返回更新后的投票详情。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            vote_session = await uow.vote_session.get_vote_session_with_details(qo.message_id)
            if not vote_session:
                raise ValueError(f"找不到与消息 ID {qo.message_id} 关联的投票会话。")

            updated_session = await uow.user_vote.delete_vote(
                user_id=qo.user_id,
                choice_index=qo.choice_index,
                vote_session=vote_session,
            )
            if not updated_session:
                raise ValueError(f"在消息 ID {qo.message_id} 的会话中找不到要删除的投票。")
            vote_options = None
            if updated_session.id:
                vote_options = await uow.vote_option.get_vote_options(updated_session.id)
            return VoteSessionService.get_vote_details_dto(updated_session, vote_options)

    async def prepare_voting_choice_data(
        self, user_id: int, thread_id: int, message_id: int
    ) -> VotingChoicePanelDto:
        """
        准备投票选择视图所需的所有数据。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 获取投票会话详情
            vote_session = await uow.vote_session.get_vote_session_with_details(message_id)

            if not vote_session or not vote_session.context_message_id:
                raise ValueError("Vote session not found, cannot prepare panel data.")

            # 获取资格数据 (并行获取当前和继承的活动)
            (
                is_eligible,
                total_message_count,
                is_validation_revoked,
            ) = await self._get_combined_eligibility_data(uow, user_id, thread_id, vote_session)

            # 处理选项和当前投票状态
            vote_options_dto = []
            current_votes = {}

            if vote_session.id:
                vote_options = await uow.vote_option.get_vote_options(vote_session.id)
                vote_details = VoteSessionService.get_vote_details_dto(vote_session, vote_options)
                vote_options_dto = vote_details.options

                # 获取用户对每个选项的投票
                user_votes = [v for v in vote_session.userVotes if v.user_id == user_id]
                for v in user_votes:
                    current_votes[v.choice_index] = v.choice

            is_vote_active = vote_session.status == 1

            return VotingChoicePanelDto(
                guild_id=vote_session.guild_id,
                thread_id=vote_session.context_thread_id,
                message_id=vote_session.context_message_id,
                is_eligible=is_eligible,
                is_vote_active=is_vote_active,
                message_count=total_message_count,
                is_validation_revoked=is_validation_revoked,
                options=vote_options_dto,
                current_votes=current_votes,
            )

    async def handle_message_creation(self, qo: UpdateUserActivityQo) -> None:
        """处理消息创建事件，增加用户活跃度。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            await uow.user_activity.update_user_activity(qo)

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
            user_activity_orm = await uow.user_activity.update_user_activity(qo)

            user_activity_dto = UserActivityDto.model_validate(user_activity_orm)
            if EligibilityService.is_eligible(user_activity_dto):
                return None

            # 找到该帖子下的所有投票会话 ID
            all_sessions_in_thread = (
                await uow.vote_session.get_all_sessions_in_thread_with_details(qo.thread_id)
            )
            session_ids = [s.id for s in all_sessions_in_thread if s.id is not None]

            # 尝试删除用户在这些会话中的所有投票
            deleted_count = await uow.user_vote.delete_all_user_votes_in_thread(
                user_id=qo.user_id, session_ids=session_ids
            )

            if deleted_count == 0:
                return None

            # 重新获取会话以确保数据最新
            all_sessions_in_thread = (
                await uow.vote_session.get_all_sessions_in_thread_with_details(qo.thread_id)
            )
            details_to_update: List[VoteDetailDto] = []
            for session in all_sessions_in_thread:
                if session.id:
                    vote_options = await uow.vote_option.get_vote_options(session.id)
                    details_to_update.append(
                        VoteSessionService.get_vote_details_dto(session, vote_options)
                    )
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
            current_session = await uow.vote_session.get_vote_session_by_context_message_id(
                message_id
            )
            if not current_session or not current_session.end_time:
                raise RuntimeError(f"无法为消息 {message_id} 找到投票会话或其结束时间。")
            old_end_time = current_session.end_time

            target_tz = self.bot.config.get("timezone", "UTC")
            new_end_time = TimeUtils.get_utc_end_time(
                duration_hours=hours_to_add, target_tz=target_tz
            )

            reopened_session = await uow.vote_session.reopen_vote_session(message_id, new_end_time)
            if not reopened_session:
                raise RuntimeError("更新数据库失败。")

            await uow.commit()

            final_session = await uow.vote_session.get_vote_session_with_details(message_id)
            if not final_session:
                raise RuntimeError("重新获取会话失败。")

            vote_options = None
            if final_session.id:
                vote_options = await uow.vote_option.get_vote_options(final_session.id)
            vote_details = VoteSessionService.get_vote_details_dto(final_session, vote_options)
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
        self,
        thread_id: int,
        message_id: int,
        hours_to_adjust: int,
        operator: discord.User | discord.Member,
    ):
        """
        处理调整投票时间的业务流程，并分派事件以更新UI。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            qo = AdjustVoteTimeQo(message_id=message_id, hours_to_adjust=hours_to_adjust)
            result_dto = await uow.vote_session.adjust_vote_time(qo)
            await uow.commit()

            if not result_dto.vote_session.context_message_id:
                raise ValueError("找不到关联的消息ID。")

            final_session = await uow.vote_session.get_vote_session_with_details(message_id)
            if not final_session:
                raise RuntimeError("重新获取会话失败。")
            vote_options = None
            if final_session.id:
                vote_options = await uow.vote_option.get_vote_options(final_session.id)
            vote_details = VoteSessionService.get_vote_details_dto(final_session, vote_options)
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
                result_dto.vote_session.end_time,
                result_dto.old_end_time,
            )

    async def tally_and_close_session(self, vote_session: VoteSessionDto) -> VoteStatusDto:
        """
        计票并关闭一个投票会话。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            if not vote_session.context_message_id:
                raise ValueError("无法计票：缺少关联的消息ID。")
            vote_session_dto = await uow.vote_session.get_vote_session_with_details(
                vote_session.context_message_id
            )

            if not vote_session_dto:
                raise ValueError(f"找不到ID为 {vote_session.id} 的投票会话")

            # 从已加载的关系中获取投票
            all_votes = vote_session_dto.userVotes
            option_results: List[OptionResult] = []
            total_approve_votes = 0
            total_reject_votes = 0

            # 单独查询投票选项
            options = await uow.vote_option.get_vote_options(vote_session.id)
            if options:
                for option in options:
                    approve = sum(
                        1
                        for v in all_votes
                        if v.choice_index == option.choice_index and v.choice == 1
                    )
                    reject = sum(
                        1
                        for v in all_votes
                        if v.choice_index == option.choice_index and v.choice == 0
                    )
                    option_results.append(
                        OptionResult(
                            choice_index=option.choice_index,
                            choice_text=option.choice_text,
                            approve_votes=approve,
                            reject_votes=reject,
                            total_votes=approve + reject,
                        )
                    )
                    total_approve_votes += approve
                    total_reject_votes += reject
            else:
                total_approve_votes = sum(1 for v in all_votes if v.choice == 1)
                total_reject_votes = sum(1 for v in all_votes if v.choice == 0)

            # 更新会话状态
            vote_session_dto.status = 0  # 已结束
            await uow.flush()

            voters_dto_list = (
                [UserVoteDto.model_validate(vote) for vote in all_votes]
                if not vote_session_dto.anonymous_flag
                else []
            )

            return VoteStatusDto(
                is_anonymous=vote_session_dto.anonymous_flag,
                realtime_flag=vote_session_dto.realtime_flag,
                notify_flag=vote_session_dto.notify_flag,
                end_time=vote_session_dto.end_time,
                status=vote_session_dto.status,
                totalVotes=len(all_votes),
                approveVotes=total_approve_votes,
                rejectVotes=total_reject_votes,
                options=option_results,
                voters=voters_dto_list,
            )
