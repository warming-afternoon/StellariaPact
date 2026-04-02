import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import discord

from StellariaPact.cogs.Voting.dto import VoteDetailDto
from StellariaPact.cogs.Voting.EligibilityService import EligibilityService
from StellariaPact.cogs.Voting.qo import (
    AdjustVoteTimeQo,
    DeleteVoteQo,
    RecordVoteQo,
    UpdateUserActivityQo,
)
from StellariaPact.dto import ConfirmationSessionDto, UserActivityDto, VoteSessionDto
from StellariaPact.models.VoteSession import VoteSession
from StellariaPact.services.VoteSessionService import VoteSessionService
from StellariaPact.share import StellariaPactBot, TimeUtils, UnitOfWork
from StellariaPact.share.auth import RoleGuard

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

    async def get_user_votes_dict(
        self, message_id: int, user_id: int
    ) -> dict[tuple[int, int], int]:
        """获取特定用户在指定投票中的选择字典 {(option_type, choice_index): choice}"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            session = await uow.vote_session.get_vote_session_with_details(message_id)
            if not session:
                return {}
            return {
                (v.option_type, v.choice_index): v.choice
                for v in session.userVotes
                if v.user_id == user_id
            }

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

            # 多选项数上限限制检查（仅针对支持票 choice==1 检查）
            if qo.choice == 1:
                current_supports = [
                    v
                    for v in vote_session.userVotes
                    if (
                        v.user_id == qo.user_id
                        and v.choice == 1
                        and v.option_type == qo.option_type
                    )
                ]
                already_supported = any(
                    v.choice_index == qo.choice_index for v in current_supports
                )
                # 如果是新的支持票，且已达上限，则阻拦
                max_choices_per_user = getattr(
                    vote_session, "max_choices_per_user", 999999
                )
                if (
                    not already_supported
                    and len(current_supports) >= max_choices_per_user
                ):
                    raise PermissionError(
                        f"您最多只能支持 {max_choices_per_user} 个选项。请先撤回其他支持。"
                    )

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

            # 加载并传入选项
            vote_options = None
            if final_session.id:
                vote_options = await uow.vote_option.get_vote_options(final_session.id)
            return VoteSessionService.get_vote_details_dto(final_session, vote_options)

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

            # 加载并传入选项
            vote_options = None
            if final_session.id:
                vote_options = await uow.vote_option.get_vote_options(final_session.id)
            return VoteSessionService.get_vote_details_dto(final_session, vote_options)

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

            # 修复：加载并传入选项
            vote_options = None
            if final_session.id:
                vote_options = await uow.vote_option.get_vote_options(final_session.id)
            return VoteSessionService.get_vote_details_dto(final_session, vote_options)

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
                option_type=qo.option_type,
                choice_index=qo.choice_index,
                vote_session=vote_session,
            )
            if not updated_session:
                raise ValueError(f"在消息 ID {qo.message_id} 的会话中找不到要删除的投票。")
            vote_options = None
            if updated_session.id:
                vote_options = await uow.vote_option.get_vote_options(updated_session.id)
            return VoteSessionService.get_vote_details_dto(updated_session, vote_options)

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

            new_end_time = TimeUtils.get_utc_end_time(duration_hours=hours_to_add)

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

    async def tally_and_close_session(self, vote_session: VoteSessionDto) -> VoteDetailDto:
        """
        计票并关闭一个投票会话。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            if not vote_session.context_message_id:
                raise ValueError("无法计票：缺少关联的消息ID。")
            vote_session_model = await uow.vote_session.get_vote_session_with_details(
                vote_session.context_message_id
            )

            if not vote_session_model:
                raise ValueError(f"找不到ID为 {vote_session.id} 的投票会话")

            # 更新会话状态为已结束
            vote_session_model.status = 0
            await uow.flush()

            # 获取选项以构建 DTO
            vote_options = None
            if vote_session_model.id:
                vote_options = await uow.vote_option.get_vote_options(vote_session_model.id)

            return uow.vote_session.get_vote_details_dto(vote_session_model, vote_options)

    async def delete_vote_option(self, message_id: int, option_id: int) -> VoteDetailDto:
        """
        逻辑删除一个投票选项，并更新投票详情的选项总数。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 获取所属的会话
            vote_session = await uow.vote_session.get_vote_session_with_details(message_id)
            if not vote_session or not vote_session.id:
                raise ValueError(f"找不到与消息 ID {message_id} 关联的投票会话。")

            # 获取当前所有选项（包括即将被删除的）
            all_options = await uow.vote_option.get_vote_options(vote_session.id)

            # 逻辑删除指定选项
            await uow.vote_option.delete_option(option_id)

            # 过滤掉被删除的选项（data_status == 0）
            remaining_options = [opt for opt in all_options if opt.data_status == 1]
            remaining_options = [opt for opt in remaining_options if opt.id != option_id]

            # 更新会话的选项总数
            await uow.vote_session.update_vote_session_total_choices(
                vote_session.id, len(remaining_options)
            )

            # 构建 DTO
            vote_details_dto = uow.vote_session.get_vote_details_dto(
                vote_session, remaining_options
            )
            await uow.commit()

            # 返回最新的 DTO
            return vote_details_dto

    async def get_vote_details_by_any_message_id(self, message_id: int) -> Optional[VoteDetailDto]:
        """
        依次从原帖、主镜像、额外镜像中查找消息ID对应的投票详情。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 查原帖
            session = await uow.vote_session.get_vote_session_with_details(message_id)

            # 查主镜像
            if not session:
                session = await uow.vote_session.get_details_by_voting_channel_message_id(
                    message_id
                )

            # 查额外镜像
            if not session:
                session = await uow.vote_session.get_details_by_mirror_message_id(
                    message_id
                )

            # 如果都没找到
            if not session or not session.id:
                return None

            # 获取选项并转换为纯粹的 DTO
            vote_options = await uow.vote_option.get_vote_options(session.id)
            return VoteSessionService.get_vote_details_dto(session, vote_options)

    async def add_mirror_record_by_context(
        self,
        context_message_id: int,
        guild_id: int,
        channel_id: int,
        new_message_id: int,
    ):
        """
        根据原帖消息ID反查出 Session ID，并写入新的镜像记录。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            session = await uow.vote_session.get_vote_session_by_context_message_id(
                context_message_id
            )
            if session and session.id:
                await uow.vote_session.add_mirror_message(
                    session_id=session.id,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    message_id=new_message_id,
                )
                await uow.commit()

    async def handle_objection_support_click(
        self, interaction: discord.Interaction, action: str = "support"
    ) -> tuple[ConfirmationSessionDto, bool]:
        """
        处理异议支持/撤回按钮点击的业务逻辑
        返回 (更新后的session DTO, 是否在本次点击后完成)
        """

        if not interaction.message or not interaction.message.id:
            raise ValueError("无法获取消息ID。")

        message_id = interaction.message.id
        user_id = interaction.user.id

        # 身份组校验
        valid_roles = ["councilModerator", "executionAuditor", "stewards", "communityBuilder"]
        if not RoleGuard.hasRoles(interaction, *valid_roles):
            raise PermissionError(
                "❌ 你没有权限参与异议附议。需要提案组/社区建设者身份组。"
            )

        session_dto = None
        is_completed = False

        async with UnitOfWork(self.bot.db_handler) as uow:
            session = await uow.confirmation_session.get_confirmation_session_by_message_id(
                message_id
            )
            if not session or session.context != "objection_support":
                raise ValueError("未找到对应的异议支持记录。")

            if session.status != 0:
                raise ValueError("该异议支持已结束或已失效。")

            # 验证 3 天有效期 (逾期直接阻断并撤销)
            now = datetime.now(timezone.utc)
            if now > session.created_at + timedelta(days=3):
                session = await uow.confirmation_session.cancel_objection_support(session)
                # 转换为 DTO 返回
                session_dto = ConfirmationSessionDto.model_validate(session)
                return session_dto, False

            parties = session.confirmed_parties or {}

            # ======= 根据 action 分流处理 =======
            if action == "support":
                if user_id in parties.values():
                    raise ValueError("你已经支持过该异议了。")

                # 调用服务层增加支持者
                session = await uow.confirmation_session.add_objection_supporter(session, user_id)
                is_completed = (session.status == 1)

                # 如果凑齐 3 人完成，把异议写入关联的主投票面板 VoteOption 表
                if is_completed:
                    main_vote_session = await uow.vote_session.get_vote_session_with_details(
                        session.target_id
                    )
                    if not main_vote_session or not main_vote_session.id:
                        raise ValueError("无法关联主投票会话，数据异常。")

                    creator_id = parties.get("发起人", user_id)
                    creator_user = None
                    if interaction.guild:
                        creator_user = interaction.guild.get_member(creator_id)
                    if not creator_user:
                        creator_user = await self.bot.fetch_user(creator_id)
                    creator_name = creator_user.display_name if creator_user else "未知用户"

                    reason_text = session.reason or "无理由说明"

                    await uow.vote_option.add_option(
                        main_vote_session.id,
                        option_type=1,
                        text=reason_text,
                        creator_id=creator_id,
                        creator_name=creator_name
                    )

                    # 更新主会话选项总数
                    all_options = await uow.vote_option.get_vote_options(main_vote_session.id)
                    await uow.vote_session.update_vote_session_total_choices(
                        main_vote_session.id, len(all_options)
                    )

            elif action == "withdraw":
                if user_id not in parties.values():
                    raise ValueError("你尚未支持过该异议。")
                
                if parties.get("发起人") == user_id:
                    raise ValueError("你是异议发起人，无法撤回支持。")

                # 移除支持者
                session = await uow.confirmation_session.remove_objection_supporter(session, user_id)
                is_completed = False

            # 转换为 DTO 返回
            session_dto = ConfirmationSessionDto.model_validate(session)

        return session_dto, is_completed
