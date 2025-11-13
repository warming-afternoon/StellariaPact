import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from sqlalchemy.exc import IntegrityError

from ...models.Announcement import Announcement
from ...share.enums.ObjectionStatus import ObjectionStatus
from ...share.enums.ProposalStatus import ProposalStatus
from ...share.enums.VoteDuration import VoteDuration
from ...share.StellariaPactBot import StellariaPactBot
from ...share.StringUtils import StringUtils
from ...share.UnitOfWork import UnitOfWork
from ..Voting.dto.VoteSessionDto import VoteSessionDto
from ..Voting.dto.VoteStatusDto import VoteStatusDto
from ..Voting.qo.CreateVoteSessionQo import CreateVoteSessionQo
from .dto.CollectionExpiredResultDto import CollectionExpiredResultDto
from .dto.ConfirmationSessionDto import ConfirmationSessionDto
from .dto.ExecuteProposalResultDto import ExecuteProposalResultDto
from .dto.HandleSupportObjectionResultDto import HandleSupportObjectionResultDto
from .dto.ObjectionDetailsDto import ObjectionDetailsDto
from .dto.ObjectionDto import ObjectionDto
from .dto.ObjectionReasonUpdateResultDto import ObjectionReasonUpdateResultDto
from .dto.ObjectionReviewResultDto import ObjectionReviewResultDto
from .dto.ObjectionVotePanelDto import ObjectionVotePanelDto
from .dto.ProposalDto import ProposalDto
from .dto.SubsequentObjectionDto import SubsequentObjectionDto
from .dto.VoteFinishedResultDto import VoteFinishedResultDto
from .qo.BuildCollectionExpiredEmbedQo import BuildCollectionExpiredEmbedQo
from .qo.BuildVoteResultEmbedQo import BuildVoteResultEmbedQo
from .qo.CreateConfirmationSessionQo import CreateConfirmationSessionQo
from .qo.CreateObjectionAndVoteSessionShellQo import CreateObjectionAndVoteSessionShellQo
from .qo.CreateObjectionQo import CreateObjectionQo
from .qo.EditObjectionReasonQo import EditObjectionReasonQo
from .qo.ObjectionSupportQo import ObjectionSupportQo
from .thread_manager import ProposalThreadManager

logger = logging.getLogger(__name__)


class ModerationLogic:
    """
    处理议事管理相关的业务流程。
    这一层负责编排 Service、分派事件、处理条件逻辑，
    并将最终结果返回给调用方。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot

    async def handle_objection_thread_creation(
        self,
        objection_id: int,
        objection_thread_id: int,
        original_proposal_thread_id: int,
    ) -> Optional[ObjectionDetailsDto]:
        """
        处理异议帖创建后的数据库更新和通知。
        成功后返回可用于派发事件的 DTO。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 更新异议记录，关联新的帖子ID
            await uow.moderation.update_objection_thread_id(objection_id, objection_thread_id)

            # 更新原提案状态为“冻结中”
            await uow.moderation.update_proposal_status_by_thread_id(
                original_proposal_thread_id, ProposalStatus.FROZEN
            )
            await uow.commit()

            # 在事务提交后，重新获取 DTO 以确保数据一致性
            return await uow.moderation.get_objection_by_thread_id(objection_thread_id)

    async def handle_raise_objection(
        self,
        user_id: int,
        target_thread_id: int,
        reason: str,
        guild_id: int,
    ) -> ObjectionVotePanelDto | SubsequentObjectionDto:
        """
        处理发起异议的第一阶段：创建数据库实体。
        - 如果为首次异议，返回一个 ObjectionVotePanelDto。
        - 如果为后续异议，返回一个 SubsequentObjectionDto。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 验证提案
            proposal = await uow.moderation.get_proposal_by_thread_id(target_thread_id)
            if not proposal:
                raise ValueError("未在指定帖子中找到关连的提案。")

            if proposal.status not in [
                ProposalStatus.DISCUSSION,
                ProposalStatus.EXECUTING,
            ]:
                raise ValueError("只能对“讨论中”或“执行中”的提案发起异议。")

            # 预取数据
            proposal_id = proposal.id
            proposal_title = proposal.title
            assert proposal_id is not None

            # 判断是否为首次异议
            existing_objections = await uow.moderation.get_objections_by_proposal_id(proposal_id)
            is_first_objection = not bool(existing_objections)

            # 准备数据并调用服务
            required_votes = 5 if is_first_objection else 10
            initial_status = (
                ObjectionStatus.COLLECTING_VOTES
                if is_first_objection
                else ObjectionStatus.PENDING_REVIEW
            )

            end_time = None
            if is_first_objection:
                end_time = datetime.now(timezone.utc) + timedelta(hours=48)

            if is_first_objection:
                # 对于首次异议，同时创建异议和投票会话
                shell_qo = CreateObjectionAndVoteSessionShellQo(
                    guild_id=guild_id,
                    proposal_id=proposal_id,
                    objector_id=user_id,
                    reason=reason,
                    required_votes=required_votes,
                    status=initial_status,
                    thread_id=target_thread_id,
                    is_anonymous=False,
                    is_realtime=True,
                    end_time=end_time,
                )
                creation_result_dto = await uow.moderation.create_objection_and_vote_session_shell(
                    shell_qo
                )
                # 准备返回给 Cog 层的 DTO 用于创建投票面板
                return ObjectionVotePanelDto(
                    objection_id=creation_result_dto.objection_id,
                    vote_session_id=creation_result_dto.vote_session_id,
                    objector_id=user_id,
                    objection_reason=reason,
                    required_votes=required_votes,
                    proposal_id=proposal_id,
                    proposal_title=proposal_title,
                    proposal_thread_id=target_thread_id,
                )
            else:
                # 对于后续异议，只创建异议记录，等待审核
                objection_qo = CreateObjectionQo(
                    proposal_id=proposal_id,
                    objector_id=user_id,
                    reason=reason,
                    required_votes=required_votes,
                    status=initial_status,
                )
                objection_dto = await uow.moderation.create_objection(objection_qo)
                # 准备返回给 Cog 层的 DTO 用于创建审核UI
                return SubsequentObjectionDto(
                    objection_id=objection_dto.id,
                    objector_id=user_id,
                    objection_reason=reason,
                    proposal_id=proposal_id,
                    proposal_title=proposal_title,
                    proposal_thread_id=target_thread_id,
                )

    async def handle_execute_proposal(
        self,
        channel_id: int,
        guild_id: int,
        user_id: int,
        user_role_ids: set[int],
    ) -> Optional[ExecuteProposalResultDto]:
        """
        处理“进入执行”命令的业务流程。
        """
        return await self._initiate_proposal_confirmation(
            channel_id=channel_id,
            guild_id=guild_id,
            user_id=user_id,
            user_role_ids=user_role_ids,
            expected_status=ProposalStatus.DISCUSSION,
            context="proposal_execution",
            error_message="提案当前状态不是“讨论中”，无法执行此操作。",
            integrity_error_message="操作失败：此提案的确认流程刚刚已被另一位管理员发起。",
        )

    async def handle_complete_proposal(
        self,
        channel_id: int,
        guild_id: int,
        user_id: int,
        user_role_ids: set[int],
    ) -> Optional[ExecuteProposalResultDto]:
        """
        处理“完成提案”命令的业务流程。
        """
        return await self._initiate_proposal_confirmation(
            channel_id=channel_id,
            guild_id=guild_id,
            user_id=user_id,
            user_role_ids=user_role_ids,
            expected_status=ProposalStatus.EXECUTING,
            context="proposal_completion",
            error_message="提案当前状态不是“执行中”，无法完成。",
            integrity_error_message="操作失败：此提案的完成流程刚刚已被另一位管理员发起。",
        )

    async def _initiate_proposal_confirmation(
        self,
        channel_id: int,
        guild_id: int,
        user_id: int,
        user_role_ids: set[int],
        expected_status: ProposalStatus,
        context: str,
        error_message: str,
        integrity_error_message: str,
    ) -> Optional[ExecuteProposalResultDto]:
        """
        发起提案确认流程的通用私有方法。
        """
        session_dto: ConfirmationSessionDto | None = None
        message_id_placeholder = 0

        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                proposal = await uow.moderation.get_proposal_by_thread_id(channel_id)
                if not proposal:
                    raise ValueError("未找到关连的提案。")
                if proposal.status != expected_status:
                    raise ValueError(error_message)

                assert proposal.id is not None

                config_roles = self.bot.config.get("roles", {})
                initiator_role_keys = [
                    key for key, val in config_roles.items() if int(val) in user_role_ids
                ]

                create_session_qo = CreateConfirmationSessionQo(
                    context=context,
                    target_id=proposal.id,
                    message_id=message_id_placeholder,
                    required_roles=["councilModerator", "executionAuditor"],
                    initiator_id=user_id,
                    initiator_role_keys=initiator_role_keys,
                )
                session_dto = await uow.moderation.create_confirmation_session(create_session_qo)

                roles_config = self.bot.config.get("roles", {})
                role_display_names = {}
                for role_key in session_dto.required_roles:
                    role_id = roles_config.get(role_key)
                    role_display_names[role_key] = str(role_id) if role_id else role_key

                await uow.commit()

        except IntegrityError:
            raise ValueError(integrity_error_message)

        if not session_dto:
            return None

        return ExecuteProposalResultDto(
            session_dto=session_dto,
            role_display_names=role_display_names,
            channel_id=channel_id,
            guild_id=guild_id,
        )

    async def update_session_message_id(self, session_id: int, message_id: int):
        """
        在一个独立的事务中更新确认会话的消息ID。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            await uow.moderation.update_confirmation_session_message_id(session_id, message_id)
            await uow.commit()

    async def handle_objection_vote_finished(
        self, session_dto: VoteSessionDto, result_dto: VoteStatusDto
    ) -> Optional[VoteFinishedResultDto]:
        """
        处理异议投票结束事件的业务逻辑。
        """
        objection_id = session_dto.objection_id
        if objection_id is None:
            logger.warning(f"投票会话 {session_dto.id} 结束，但没有关联的异议ID。")
            return None

        try:
            if result_dto.voters:
                logger.debug(f"Voters data: {[v.dict() for v in result_dto.voters]}")

            # 用于存储从事务中提取的数据
            extracted_data = {}

            async with UnitOfWork(self.bot.db_handler) as uow:
                # 获取关联数据
                objection = await uow.moderation.get_objection_by_id(objection_id)
                if not objection:
                    raise ValueError(f"找不到ID为 {objection_id} 的异议。")

                proposal = await uow.moderation.get_proposal_by_id(objection.proposal_id)
                if not proposal:
                    raise ValueError(f"找不到异议 {objection_id} 关联的提案。")

                # 判断投票结果并更新状态
                is_passed = result_dto.approveVotes > result_dto.rejectVotes
                objection.status = (
                    ObjectionStatus.PASSED if is_passed else ObjectionStatus.REJECTED
                )

                if is_passed:
                    # 异议通过，原提案被否决
                    proposal.status = ProposalStatus.REJECTED
                else:
                    # 异议失败，原提案解冻
                    if proposal.status == ProposalStatus.FROZEN:
                        proposal.status = ProposalStatus.DISCUSSION

                uow.session.add(objection)
                uow.session.add(proposal)

                # 预取所有需要的数据
                guild_id = self.bot.config.get("guild_id")
                if not guild_id:
                    raise RuntimeError("未在 config.json 中配置 'guild_id'。")
                assert objection.id is not None, "Objection ID cannot be None for result embed"

                publicity_channel_id_str = self.bot.config.get("channels", {}).get(
                    "objection_publicity"
                )

                # 将所有需要在事务外使用的数据存入字典
                extracted_data = {
                    "proposal_title": proposal.title,
                    "proposal_thread_id": proposal.discussion_thread_id,
                    "objection_id": objection.id,
                    "objector_id": objection.objector_id,
                    "objection_reason": objection.reason,
                    "objection_thread_id": objection.objection_thread_id,
                    "is_passed": is_passed,
                    "guild_id": guild_id,
                    "notification_channel_id": int(publicity_channel_id_str)
                    if publicity_channel_id_str
                    else None,
                }

                # 提交事务
                await uow.commit()

            result_qo = BuildVoteResultEmbedQo(
                proposal_title=extracted_data["proposal_title"],
                proposal_thread_url=f"https://discord.com/channels/{extracted_data['guild_id']}/{extracted_data['proposal_thread_id']}",
                objection_id=extracted_data["objection_id"],
                objector_id=extracted_data["objector_id"],
                objection_reason=extracted_data["objection_reason"],
                objection_thread_url=f"https://discord.com/channels/{extracted_data['guild_id']}/{extracted_data['objection_thread_id']}"
                if extracted_data["objection_thread_id"]
                else None,
                is_passed=extracted_data["is_passed"],
                approve_votes=result_dto.approveVotes,
                reject_votes=result_dto.rejectVotes,
                total_votes=result_dto.totalVotes,
            )

            approve_voter_ids = None
            reject_voter_ids = None
            if not result_dto.is_anonymous and result_dto.voters:
                approve_voter_ids = [v.user_id for v in result_dto.voters if v.choice == 1]
                reject_voter_ids = [v.user_id for v in result_dto.voters if v.choice == 0]

            return VoteFinishedResultDto(
                embed_qo=result_qo,
                is_passed=extracted_data["is_passed"],
                original_proposal_thread_id=extracted_data["proposal_thread_id"],
                objection_thread_id=extracted_data["objection_thread_id"],
                notification_channel_id=extracted_data["notification_channel_id"],
                original_vote_message_id=session_dto.context_message_id,
                approve_voter_ids=approve_voter_ids,
                reject_voter_ids=reject_voter_ids,
            )

        except (ValueError, RuntimeError) as e:
            logger.error(f"处理异议投票结束事件 (异议ID: {objection_id}) 时发生逻辑错误: {e}")
            return None
        except Exception as e:
            logger.exception(f"处理异议投票结束事件 (异议ID: {objection_id}) 时发生意外错误: {e}")
            return None

    async def handle_objection_collection_expired(
        self, session_dto: VoteSessionDto, result_dto: VoteStatusDto
    ) -> Optional[CollectionExpiredResultDto]:
        """
        处理异议支持票收集到期事件。
        """
        objection_id = session_dto.objection_id
        if not objection_id:
            logger.warning(f"投票会话 {session_dto.id} 到期，但没有关联的异议ID。")
            return None

        try:
            extracted_data = {}
            async with UnitOfWork(self.bot.db_handler) as uow:
                objection = await uow.moderation.get_objection_by_id(objection_id)
                if not objection:
                    raise ValueError(f"找不到ID为 {objection_id} 的异议。")

                proposal = await uow.moderation.get_proposal_by_id(objection.proposal_id)
                if not proposal:
                    raise ValueError(f"找不到异议 {objection_id} 关联的提案。")

                # 将异议状态更新为“已否决”
                await uow.moderation.update_objection_status(
                    objection_id, ObjectionStatus.REJECTED
                )

                # 预取数据
                guild_id = self.bot.config.get("guild_id")
                if not guild_id:
                    raise RuntimeError("未在 config.json 中配置 'guild_id'。")

                publicity_channel_id_str = self.bot.config.get("channels", {}).get(
                    "objection_publicity"
                )

                extracted_data = {
                    "proposal_title": proposal.title,
                    "proposal_thread_id": proposal.discussion_thread_id,
                    "objector_id": objection.objector_id,
                    "objection_reason": objection.reason,
                    "final_votes": result_dto.totalVotes,
                    "required_votes": objection.required_votes,
                    "guild_id": guild_id,
                    "notification_channel_id": int(publicity_channel_id_str)
                    if publicity_channel_id_str
                    else None,
                }
                await uow.commit()

            # 构建 QO 和 DTO
            embed_qo = BuildCollectionExpiredEmbedQo(
                proposal_title=extracted_data["proposal_title"],
                proposal_url=f"https://discord.com/channels/{extracted_data['guild_id']}/{extracted_data['proposal_thread_id']}",
                objector_id=extracted_data["objector_id"],
                objector_display_name=f"<@{extracted_data['objector_id']}>",
                objection_reason=extracted_data["objection_reason"],
                final_votes=extracted_data["final_votes"],
                required_votes=extracted_data["required_votes"],
            )

            return CollectionExpiredResultDto(
                embed_qo=embed_qo,
                notification_channel_id=extracted_data["notification_channel_id"],
                original_vote_message_id=session_dto.context_message_id,
            )

        except (ValueError, RuntimeError) as e:
            logger.error(f"处理异议 {objection_id} 支持票收集到期事件时发生逻辑错误: {e}")
            return None
        except Exception as e:
            logger.error(
                f"处理异议 {objection_id} 支持票收集到期事件时发生意外错误: {e}", exc_info=True
            )
            return None

    async def handle_announcement_finished(self, announcement: Announcement):
        """
        处理公示结束事件的业务逻辑。
        """
        logger.debug(
            f"接收到公示结束事件，帖子ID: {announcement.discussion_thread_id}, "
            f"公示标题: {announcement.title}"
        )
        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                await uow.moderation.update_proposal_status_by_thread_id(
                    thread_id=announcement.discussion_thread_id,
                    status=ProposalStatus.EXECUTING,
                )
                await uow.commit()
        except Exception as e:
            logger.error(
                f"处理公示结束事件时发生错误 (帖子ID: {announcement.discussion_thread_id}): {e}",
                exc_info=True,
            )

    async def handle_support_objection(
        self, qo: ObjectionSupportQo
    ) -> HandleSupportObjectionResultDto:
        """
        处理对异议的支持操作。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            result_dto = await uow.moderation.objection_support(qo)

            # 根据服务层的返回结果，处理业务逻辑（状态变更、事件分发）
            goal_reached_first_time = (
                result_dto.user_action_result == "supported"
                and result_dto.objection_status != ObjectionStatus.VOTING
                and result_dto.is_goal_reached
            )

            if goal_reached_first_time:
                # 状态变更：收集票数 -> 正式投票
                await uow.moderation.update_objection_status(
                    result_dto.objection_id, ObjectionStatus.VOTING
                )
                # 事件分发
                self.bot.dispatch("objection_goal_reached", result_dto)

            # 提交事务
            await uow.commit()

            # 将从服务层获取的 DTO 返回给上层 (View)
            return result_dto

    async def handle_withdraw_support(
        self, qo: ObjectionSupportQo
    ) -> HandleSupportObjectionResultDto:
        """
        处理撤回对异议的支持。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 调用服务层，获取DTO
            result_dto = await uow.moderation.objection_support(qo)

            # 根据服务层的返回结果，处理状态变更
            goal_lost = (
                result_dto.user_action_result == "withdrew"
                and result_dto.objection_status == ObjectionStatus.VOTING
                and not result_dto.is_goal_reached
            )
            if goal_lost:
                # 状态变更：正式投票 -> 收集票数
                await uow.moderation.update_objection_status(
                    result_dto.objection_id, ObjectionStatus.COLLECTING_VOTES
                )

            # 提交事务
            await uow.commit()

            # 将从服务层获取的完整 DTO 返回给上层 (View)
            return result_dto

    async def handle_approve_objection(
        self, objection_id: int, moderator_id: int, reason: str, guild_id: int
    ) -> ObjectionReviewResultDto:
        """
        处理批准异议的逻辑。
        """
        try:
            panel_dto: ObjectionVotePanelDto | None = None
            objection_dto_for_result: ObjectionDto | None = None
            proposal_dto_for_result: ProposalDto | None = None

            async with UnitOfWork(self.bot.db_handler) as uow:
                objection = await uow.moderation.get_objection_by_id(objection_id)
                if not objection or objection.status != ObjectionStatus.PENDING_REVIEW:
                    raise ValueError("此异议未处于审核状态，无法被批准。")

                proposal = await uow.moderation.get_proposal_by_id(objection.proposal_id)
                if not proposal:
                    raise ValueError("找不到关联的提案，操作中止。")

                # 类型断言，确保后续操作安全
                assert objection.id is not None
                assert proposal.id is not None
                assert proposal.discussion_thread_id is not None

                # 为此异议创建新的投票会话
                end_time = datetime.now(timezone.utc) + timedelta(hours=48)
                vote_qo = CreateVoteSessionQo(
                    guild_id=guild_id,
                    thread_id=proposal.discussion_thread_id,
                    objection_id=objection.id,
                    context_message_id=0,  # 占位符，将在UI创建后更新
                    end_time=end_time,
                )
                vote_session_dto = await uow.voting.create_vote_session(vote_qo)

                # 更新异议状态
                await uow.moderation.update_objection_status(
                    objection_id, ObjectionStatus.COLLECTING_VOTES
                )

                # 准备用于事件分派的 DTO
                panel_dto = ObjectionVotePanelDto(
                    objection_id=objection.id,
                    vote_session_id=vote_session_dto.id,
                    objector_id=objection.objector_id,
                    objection_reason=objection.reason,
                    required_votes=objection.required_votes,
                    proposal_id=proposal.id,
                    proposal_title=proposal.title,
                    proposal_thread_id=proposal.discussion_thread_id,
                )
                objection_dto_for_result = ObjectionDto.from_orm(objection)
                proposal_dto_for_result = ProposalDto.from_orm(proposal)

                await uow.commit()

            # 使用 DTO 对象分派事件
            if panel_dto:
                self.bot.dispatch("create_objection_vote_panel", panel_dto)

            return ObjectionReviewResultDto(
                success=True,
                message="操作成功",
                objection=objection_dto_for_result,
                proposal=proposal_dto_for_result,
                moderator_id=moderator_id,
                reason=reason,
                is_approve=True,
            )
        except ValueError as e:
            return ObjectionReviewResultDto(success=False, message=str(e))

    async def handle_update_objection_reason(
        self, qo: EditObjectionReasonQo
    ) -> ObjectionReasonUpdateResultDto:
        """
        处理更新异议理由的业务逻辑
        """
        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                # 更新数据库
                objection = await uow.moderation.update_objection_reason(
                    qo.objection_id, qo.new_reason, qo.interaction.user.id
                )

                # 从数据库中提取所需数据
                proposal = await uow.moderation.get_proposal_by_id(objection.proposal_id)
                if not proposal:
                    raise ValueError(f"找不到异议 {qo.objection_id} 关联的提案。")

                if not qo.interaction.guild:
                    raise RuntimeError("交互不包含服务器信息。")

                # 将数据打包到 DTO
                return ObjectionReasonUpdateResultDto(
                    success=True,
                    message="异议理由已成功更新。",
                    guild_id=qo.interaction.guild.id,
                    review_thread_id=objection.review_thread_id,
                    objection_id=objection.id,
                    proposal_id=proposal.id,
                    proposal_title=proposal.title,
                    proposal_thread_id=proposal.discussion_thread_id,
                    objector_id=objection.objector_id,
                    new_reason=objection.reason,
                )
        except (PermissionError, ValueError, RuntimeError) as e:
            logger.warning(f"更新异议理由时发生错误: {e}")
            return ObjectionReasonUpdateResultDto(success=False, message=str(e))
        except Exception as e:
            logger.error(f"更新异议 {qo.objection_id} 理由时发生未知错误: {e}", exc_info=True)
            return ObjectionReasonUpdateResultDto(
                success=False, message="更新理由时发生未知错误，请联系管理员。"
            )

    async def handle_reject_objection(
        self, objection_id: int, moderator_id: int, reason: str
    ) -> ObjectionReviewResultDto:
        """
        处理驳回异议的逻辑
        """
        try:
            objection_dto: ObjectionDto | None = None
            proposal_dto: ProposalDto | None = None
            async with UnitOfWork(self.bot.db_handler) as uow:
                objection = await uow.moderation.get_objection_by_id(objection_id)
                if not objection or objection.status != ObjectionStatus.PENDING_REVIEW:
                    raise ValueError("此异议未处于审核状态，无法被驳回。")

                proposal = await uow.moderation.get_proposal_by_id(objection.proposal_id)
                if not proposal:
                    raise ValueError("找不到关联的提案，操作中止。")

                await uow.moderation.update_objection_status(
                    objection_id, ObjectionStatus.REJECTED
                )
                objection_dto = ObjectionDto.from_orm(objection)
                proposal_dto = ProposalDto.from_orm(proposal)
                await uow.commit()

            return ObjectionReviewResultDto(
                success=True,
                message="操作成功",
                objection=objection_dto,
                proposal=proposal_dto,
                moderator_id=moderator_id,
                reason=reason,
                is_approve=False,
            )
        except ValueError as e:
            return ObjectionReviewResultDto(success=False, message=str(e))

    async def process_new_discussion_thread(self, thread: discord.Thread) -> None:
        """
        处理一个新发现的、未被记录的讨论区帖子<br>
        该方法会先判断帖子是提案还是异议，然后执行相应的处理
        """
        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                # 检查它是否是一个已知的异议帖
                objection = await uow.moderation.get_objection_by_thread_id(thread.id)
                if objection:
                    # logger.debug(f"帖子 {thread.id} 是一个已知的异议帖，跳过处理")
                    return

                # 检查它是否已经是一个已知的提案帖
                proposal = await uow.moderation.get_proposal_by_thread_id(thread.id)
                if proposal:
                    # logger.debug(f"提案 (帖子 ID: {thread.id}) 已存在，跳过处理")
                    return

            # 如果以上都不是，则认定为新提案，执行创建流程
            logger.info(f"发现新的提案帖: {thread.name} ({thread.id})。正在处理...")

            # 获取首楼内容和提案人信息
            content = await StringUtils.extract_starter_content(thread)
            if not content:
                logger.warning(f"无法获取帖子 {thread.id} 的首楼内容，中止提案创建。")
                return

            proposer_id = StringUtils.extract_proposer_id_from_content(content)
            if not proposer_id:
                proposer_id = thread.owner_id
            clean_title = StringUtils.clean_title(thread.name)

            # 在数据库中创建提案
            proposal_dto = None
            async with UnitOfWork(self.bot.db_handler) as uow:
                proposal_dto = await uow.moderation.create_proposal(
                    thread.id, proposer_id, clean_title, content
                )
                await uow.commit()

            # 如果创建了 *新* 的提案，则更新UI并派发事件
            if proposal_dto:
                logger.info(f"已处理新提案 '{clean_title}' (帖子 ID: {thread.id})。")
                # 更新帖子外观（标签、标题前缀）
                thread_manager = ProposalThreadManager(self.bot.config)
                await thread_manager.update_status(thread, "discussion")
                # 派发事件，让 Voting cog 创建投票面板
                self.bot.dispatch(
                    "proposal_created",
                    proposal_dto,
                    [],  # options - 空列表，因为自动创建的提案没有投票选项
                    VoteDuration.PROPOSAL_DEFAULT,
                    True,  # anonymous
                    True,  # realtime
                    True,  # notify
                    True,  # create_in_voting_channel
                    True,  # notify_creation_role
                )

        except Exception as e:
            logger.error(
                f"处理新讨论帖 {thread.id} 时发生错误: {e}",
                exc_info=True,
            )

    async def handle_proposal_execution_confirmed(self, proposal_id: int) -> ProposalDto | None:
        """
        处理提案进入执行状态的确认事件。
        """
        return await self._handle_proposal_status_change_confirmed(
            proposal_id, ProposalStatus.EXECUTING
        )

    async def handle_proposal_completion_confirmed(self, proposal_id: int) -> ProposalDto | None:
        """
        处理提案完成的确认事件。
        """
        return await self._handle_proposal_status_change_confirmed(
            proposal_id, ProposalStatus.FINISHED
        )

    async def _handle_proposal_status_change_confirmed(
        self, proposal_id: int, new_status: ProposalStatus
    ) -> ProposalDto | None:
        """
        通用方法：处理提案状态变更的确认事件。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            proposal = await uow.moderation.get_proposal_by_id(proposal_id)
            if not proposal:
                logger.warning(
                    f"无法找到ID为 {proposal_id} 的提案，无法更新状态为 {new_status.name}。"
                )
                return None

            proposal.status = new_status
            uow.session.add(proposal)
            await uow.commit()
            await uow.session.refresh(proposal)

            return ProposalDto.model_validate(proposal)
