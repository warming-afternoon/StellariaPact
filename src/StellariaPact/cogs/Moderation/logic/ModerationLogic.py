import asyncio
import logging
from typing import Optional

from sqlalchemy.exc import IntegrityError

from ....cogs.Voting.dto.VoteSessionDto import VoteSessionDto
from ....cogs.Voting.dto.VoteStatusDto import VoteStatusDto
from ....models.Announcement import Announcement
from ....share.enums.ObjectionStatus import ObjectionStatus
from ....share.enums.ProposalStatus import ProposalStatus
from ....share.StellariaPactBot import StellariaPactBot
from ....share.UnitOfWork import UnitOfWork
from ..dto.ConfirmationSessionDto import ConfirmationSessionDto
from ..dto.ExecuteProposalResultDto import ExecuteProposalResultDto
from ..dto.HandleSupportObjectionResultDto import HandleSupportObjectionResultDto
from ..dto.RaiseObjectionResultDto import RaiseObjectionResultDto
from ..dto.VoteFinishedResultDto import VoteFinishedResultDto
from ..qo.BuildVoteResultEmbedQo import BuildVoteResultEmbedQo
from ..qo.CreateConfirmationSessionQo import CreateConfirmationSessionQo
from ..qo.CreateObjectionAndVoteSessionShellQo import (
    CreateObjectionAndVoteSessionShellQo,
)
from ..qo.HandleSupportObjectionQo import HandleSupportObjectionQo

logger = logging.getLogger(__name__)


class ModerationLogic:
    async def handle_objection_thread_creation(
        self,
        objection_id: int,
        objection_thread_id: int,
        original_proposal_thread_id: int,
    ):
        """
        处理异议帖创建后的数据库更新和通知。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 1. 更新异议记录，关联新的帖子ID
            await uow.moderation.update_objection_thread_id(objection_id, objection_thread_id)

            # 2. 更新原提案状态为“冻结中”
            await uow.moderation.update_proposal_status_by_thread_id(
                original_proposal_thread_id, ProposalStatus.FROZEN
            )
            await uow.commit()

    """
    处理议事管理相关的业务流程。
    这一层负责编排 Service、分派事件、处理条件逻辑，
    并将最终结果返回给调用方。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot

    async def handle_raise_objection(
        self,
        user_id: int,
        target_thread_id: int,
        reason: str,
    ) -> RaiseObjectionResultDto:
        """
        处理发起异议的第一阶段：创建数据库实体。
        返回一个包含所有后续UI操作所需数据的DTO。
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

            proposal_id = proposal.id
            proposal_title = proposal.title
            assert proposal_id is not None

            # 2. 判断是否为首次异议
            existing_objections = await uow.moderation.get_objections_by_proposal_id(proposal_id)
            is_first_objection = not bool(existing_objections)

            # 3. 准备数据并调用服务
            required_votes = 5 if is_first_objection else 10
            initial_status = (
                ObjectionStatus.COLLECTING_VOTES
                if is_first_objection
                else ObjectionStatus.PENDING_REVIEW
            )

            qo = CreateObjectionAndVoteSessionShellQo(
                proposal_id=proposal_id,
                objector_id=user_id,
                reason=reason,
                required_votes=required_votes,
                status=initial_status,
                thread_id=target_thread_id,
                is_anonymous=False,
                is_realtime=True,
            )
            creation_result_dto = await uow.moderation.create_objection_and_vote_session_shell(qo)

            # 4. 提交事务
            await uow.commit()

            # 5. 准备返回给 Cog 层的 DTO
            return RaiseObjectionResultDto(
                is_first_objection=is_first_objection,
                objection_id=creation_result_dto.objection_id,
                vote_session_id=creation_result_dto.vote_session_id,
                objector_id=user_id,
                objection_reason=reason,
                required_votes=required_votes,
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
        处理“进入执行”命令的完整业务流程。
        """
        session_dto: ConfirmationSessionDto | None = None
        message_id_placeholder = 0  # 临时占位符

        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                # 1. 读取提案信息
                proposal = await uow.moderation.get_proposal_by_thread_id(channel_id)
                if not proposal:
                    raise ValueError("未找到关连的提案。")
                if proposal.status != ProposalStatus.DISCUSSION:
                    raise ValueError("提案当前状态不是“讨论中”，无法执行此操作。")

                assert proposal.id is not None

                # 2. 创建确认会话
                config_roles = self.bot.config.get("roles", {})
                initiator_role_keys = [
                    key for key, val in config_roles.items() if int(val) in user_role_ids
                ]

                create_session_qo = CreateConfirmationSessionQo(
                    context="proposal_execution",
                    target_id=proposal.id,
                    message_id=message_id_placeholder,  # 稍后更新
                    required_roles=["councilModerator", "executionAuditor"],
                    initiator_id=user_id,
                    initiator_role_keys=initiator_role_keys,
                )
                session_dto = await uow.moderation.create_confirmation_session(create_session_qo)

                # 3. 准备返回给 Cog 层的数据
                roles_config = self.bot.config.get("roles", {})
                role_display_names = {}
                for role_key in session_dto.required_roles:
                    role_id = roles_config.get(role_key)
                    role_display_names[role_key] = str(role_id) if role_id else role_key

                # 4. 提交事务
                await uow.commit()

        except IntegrityError:
            # 竞态条件：其他管理员同时操作
            raise ValueError("操作失败：此提案的确认流程刚刚已被另一位管理员发起。")

        if not session_dto:
            # 正常情况下不应发生
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

    async def update_vote_session_message_id(self, session_id: int, message_id: int):
        """
        更新投票会话的消息ID
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            await uow.moderation.update_vote_session_message_id(session_id, message_id)
            await uow.commit()

    async def handle_objection_vote_finished(
        self, session_dto: VoteSessionDto, result_dto: VoteStatusDto
    ) -> Optional[VoteFinishedResultDto]:
        """
        处理异议投票结束事件的业务逻辑。
        """
        objection_id = session_dto.objectionId
        if objection_id is None:
            logger.warning(f"投票会话 {session_dto.id} 结束，但没有关联的异议ID。")
            return None

        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                # 1. 判断投票结果
                is_passed = result_dto.approveVotes > result_dto.rejectVotes
                new_status = ObjectionStatus.PASSED if is_passed else ObjectionStatus.REJECTED

                # 2. 更新异议状态
                await uow.moderation.update_objection_status(objection_id, new_status)
                objection = await uow.moderation.get_objection_by_id(objection_id)
                proposal = (
                    await uow.moderation.get_proposal_by_id(objection.proposalId)
                    if objection
                    else None
                )
                await uow.commit()

            # 准备返回给 Cog 层的数据
            if not objection or not proposal:
                logger.error(f"无法为已结束的异议 {objection_id} 找到完整的上下文信息。")
                return None

            guild_id = self.bot.config.get("guild_id")
            if not guild_id:
                logger.error("未在 config.json 中配置 'guild_id'。")
                return None
            assert objection.id is not None, "Objection ID cannot be None for result embed"

            result_qo = BuildVoteResultEmbedQo(
                proposal_title=proposal.title,
                proposal_thread_url=f"https://discord.com/channels/{guild_id}/{proposal.discussionThreadId}",
                objection_id=objection.id,
                objection_reason=objection.reason,
                is_passed=is_passed,
                approve_votes=result_dto.approveVotes,
                reject_votes=result_dto.rejectVotes,
                total_votes=result_dto.totalVotes,
            )

            publicity_channel_id_str = self.bot.config.get("channels", {}).get(
                "objection_publicity"
            )
            channel_id = int(publicity_channel_id_str) if publicity_channel_id_str else None

            return VoteFinishedResultDto(
                embed_qo=result_qo,
                channel_id=channel_id,
                message_id=session_dto.contextMessageId,
            )

        except Exception as e:
            logger.exception(f"处理异议投票结束事件 (异议ID: {objection_id}) 时发生错误: {e}")
            return None

    async def handle_announcement_finished(self, announcement: Announcement):
        """
        处理公示结束事件的业务逻辑。
        """
        logger.debug(
            f"接收到公示结束事件，帖子ID: {announcement.discussionThreadId}, "
            f"公示标题: {announcement.title}"
        )
        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                await uow.moderation.update_proposal_status_by_thread_id(
                    thread_id=announcement.discussionThreadId,
                    status=ProposalStatus.EXECUTING,
                )
                await uow.commit()
        except Exception as e:
            logger.error(
                f"处理公示结束事件时发生错误 (帖子ID: {announcement.discussionThreadId}): {e}",
                exc_info=True,
            )

    async def handle_support_objection(
        self, qo: HandleSupportObjectionQo
    ) -> HandleSupportObjectionResultDto:
        """
        处理支持异议的业务逻辑，包括数据库操作和状态检查。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            # --- 读取和验证 ---
            vote_session = await uow.voting.get_vote_session_by_context_message_id(qo.message_id)
            if not vote_session or not vote_session.id or not vote_session.objectionId:
                raise ValueError("错误：找不到对应的投票会话或会话未关联任何异议。")

            objection_id = vote_session.objectionId

            # 并行获取数据
            (
                objection,
                existing_vote,
                votes_count_before_vote,
            ) = await asyncio.gather(
                uow.moderation.get_objection_by_id(objection_id),
                uow.voting.get_user_vote_by_session_id(
                    user_id=qo.user_id, session_id=vote_session.id
                ),
                uow.voting.get_vote_count_by_session_id(vote_session.id),
            )

            if not objection:
                raise ValueError("错误：找不到相关的异议。")

            if existing_vote:
                return HandleSupportObjectionResultDto(
                    votes_count=votes_count_before_vote,
                    required_votes=objection.requiredVotes,
                    is_goal_reached=(votes_count_before_vote >= objection.requiredVotes),
                    is_vote_recorded=False,
                )

            # ---  写入操作 ---
            await uow.voting.create_vote(session_id=vote_session.id, user_id=qo.user_id, choice=1)

            # --- 进行业务判断 ---
            votes_count = votes_count_before_vote + 1
            is_goal_reached = votes_count >= objection.requiredVotes

            result_dto_data = {
                "votes_count": votes_count,
                "required_votes": objection.requiredVotes,
                "is_goal_reached": is_goal_reached,
                "is_vote_recorded": True,
            }

            if is_goal_reached:
                await uow.moderation.update_objection_status(objection_id, ObjectionStatus.VOTING)
                proposal = await uow.moderation.get_proposal_by_id(objection.proposalId)
                if not proposal:
                    raise ValueError(
                        f"在处理异议 {objection_id} 时找不到关联的提案 {objection.proposalId}"
                    )

                # 填充用于事件分派的数据
                result_dto_data["objection_id"] = objection.id
                result_dto_data["proposal_id"] = proposal.id
                result_dto_data["proposal_title"] = proposal.title
                result_dto_data["proposal_discussion_thread_id"] = proposal.discussionThreadId
                result_dto_data["objector_id"] = objection.objector_id
                result_dto_data["objection_reason"] = objection.reason

                dispatch_dto = HandleSupportObjectionResultDto.model_validate(result_dto_data)

            # --- 4. 提交和返回 ---
            await uow.commit()

            # 在事务成功后分派事件
            if is_goal_reached:
                self.bot.dispatch("objection_goal_reached", dispatch_dto)

            return HandleSupportObjectionResultDto.model_validate(result_dto_data)

    async def handle_withdraw_support(
        self, qo: HandleSupportObjectionQo
    ) -> HandleSupportObjectionResultDto:
        """
        处理撤回支持异议的业务逻辑。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            # --- 1. 读取和验证 ---
            vote_session = await uow.voting.get_vote_session_by_context_message_id(qo.message_id)
            if not vote_session or not vote_session.id or not vote_session.objectionId:
                raise ValueError("错误：找不到对应的投票会话或会话未关联任何异议。")

            objection = await uow.moderation.get_objection_by_id(vote_session.objectionId)
            if not objection:
                raise ValueError(f"错误：找不到ID为 {vote_session.objectionId} 的异议。")

            required_votes = objection.requiredVotes

            # --- 2. 尝试删除投票 ---
            await uow.voting.delete_user_vote_by_message_id(
                user_id=qo.user_id, message_id=qo.message_id
            )

            # --- 3. 获取最新票数并进行业务判断 ---
            votes_count = await uow.voting.get_vote_count_by_session_id(vote_session.id)
            is_goal_reached = votes_count >= required_votes

            # 如果之前是达到目标的，现在没达到，需要更新异议状态
            if objection.status == ObjectionStatus.VOTING and not is_goal_reached:
                assert objection.id is not None
                await uow.moderation.update_objection_status(
                    objection.id, ObjectionStatus.COLLECTING_VOTES
                )

            # --- 4. 提交和返回 ---
            await uow.commit()

            return HandleSupportObjectionResultDto(
                votes_count=votes_count,
                required_votes=required_votes,
                is_goal_reached=is_goal_reached,
                is_vote_recorded=False,  # 撤回后，投票记录必定不存在
            )
