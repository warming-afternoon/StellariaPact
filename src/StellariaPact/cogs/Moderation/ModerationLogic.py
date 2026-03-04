import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from sqlalchemy.exc import IntegrityError

from StellariaPact.cogs.Moderation.dto import ExecuteProposalResultDto
from StellariaPact.cogs.Moderation.qo import CreateConfirmationSessionQo
from StellariaPact.cogs.Moderation.thread_manager import ProposalThreadManager
from StellariaPact.dto import ConfirmationSessionDto, ProposalDto
from StellariaPact.models import Announcement
from StellariaPact.services.VoteSessionService import VoteSessionService
from StellariaPact.share import DiscordUtils, StellariaPactBot, StringUtils, UnitOfWork
from StellariaPact.share.enums import ProposalStatus, VoteDuration

logger = logging.getLogger(__name__)


class ModerationLogic:
    """
    处理议事管理相关的业务流程。
    这一层负责编排 Service、分派事件、处理条件逻辑，
    并将最终结果返回给调用方。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.thread_manager = ProposalThreadManager(bot.config)

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
            expected_status=[ProposalStatus.DISCUSSION],
            context="proposal_execution",
            error_message="提案当前状态不是“讨论中”，无法执行此操作。",
            integrity_error_message="操作失败：此提案的确认流程刚刚已被另一位管理员发起。",
            check_24h=True,
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
            expected_status=[ProposalStatus.DISCUSSION, ProposalStatus.EXECUTING],
            context="proposal_completion",
            error_message="提案当前状态不是“讨论中”或“执行中”，无法完成。",
            integrity_error_message="操作失败：此提案的完成流程刚刚已被另一位管理员发起。",
            check_24h=True,
        )

    async def handle_abandon_proposal(
        self,
        channel_id: int,
        guild_id: int,
        user_id: int,
        user_role_ids: set[int],
        reason: str,
    ) -> Optional[ExecuteProposalResultDto]:
        """
        处理“废弃提案”命令的业务流程。
        允许废弃 [讨论中/冻结中/执行中/异议中] 状态的帖子。
        """
        return await self._initiate_proposal_confirmation(
            channel_id=channel_id,
            guild_id=guild_id,
            user_id=user_id,
            user_role_ids=user_role_ids,
            expected_status=[
                ProposalStatus.DISCUSSION,
                ProposalStatus.FROZEN,
                ProposalStatus.EXECUTING,
                ProposalStatus.UNDER_OBJECTION
            ],
            context="proposal_abandonment",
            error_message="提案当前状态不是“讨论中”、“冻结中”、“执行中”或“异议中”，无法废弃。",
            integrity_error_message="操作失败：此提案的废弃流程刚刚已被另一位管理员发起。",
            reason=reason,
            check_24h=True,
        )

    async def handle_rediscuss_proposal(
        self, channel_id: int, guild_id: int, user_id: int, user_role_ids: set[int]
    ) -> Optional[ExecuteProposalResultDto]:
        """处理"重新讨论"命令的业务流程。"""

        # 获取基础状态信息（短事务）
        async with UnitOfWork(self.bot.db_handler) as uow:
            proposal = await uow.proposal.get_proposal_by_thread_id(channel_id)
            if not proposal:
                raise ValueError("未找到关连的提案。")
            current_status = ProposalStatus(proposal.status)

        # 若当前为“异议中”，先执行阻断校验
        if current_status == ProposalStatus.UNDER_OBJECTION:
            await self._verify_objection_blockers(channel_id)

        # 发起通用确认流程
        all_statuses = [
            ProposalStatus.DISCUSSION,
            ProposalStatus.EXECUTING,
            ProposalStatus.FROZEN,
            ProposalStatus.ABANDONED,
            ProposalStatus.REJECTED,
            ProposalStatus.FINISHED,
            ProposalStatus.UNDER_OBJECTION,
        ]
        return await self._initiate_proposal_confirmation(
            channel_id=channel_id,
            guild_id=guild_id,
            user_id=user_id,
            user_role_ids=user_role_ids,
            expected_status=all_statuses,
            context="proposal_rediscuss",
            error_message="提案当前状态异常，无法重新讨论。",
            integrity_error_message="操作失败：此提案的确认流程刚刚已被另一位管理员发起。",
        )

    async def _verify_objection_blockers(self, thread_id: int):
        """校验是否存在阻碍提案恢复讨论的异议。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 获取该讨论区下的所有投票会话，筛选出其中的异议会话和选项，并统计投票结果
            sessions = await uow.vote_session.get_all_sessions_in_thread_with_details(thread_id)
            if not sessions:
                return

            session_ids = [s.id for s in sessions if s.id is not None]
            objection_options = await uow.vote_option.get_options_by_session_ids(session_ids, 1)
            if not objection_options:
                return

            session_map = {s.id: s for s in sessions if s.id is not None}
            now = datetime.now(timezone.utc)

            for option in objection_options:
                session = session_map.get(option.session_id)
                if not session:
                    continue

                created_at = option.created_at
                if now - created_at < timedelta(hours=12):
                    raise ValueError(f"无法操作：异议「{option.choice_text}」发布未满 12 小时。")

                approve_votes = sum(
                    1
                    for vote in session.userVotes
                    if vote.option_type == 1
                    and vote.choice_index == option.choice_index
                    and vote.choice == 1
                )
                reject_votes = sum(
                    1
                    for vote in session.userVotes
                    if vote.option_type == 1
                    and vote.choice_index == option.choice_index
                    and vote.choice == 0
                )
                if approve_votes > reject_votes:
                    raise ValueError(
                        f"无法操作：异议「{option.choice_text}」目前赞成票居多 ({approve_votes} vs {reject_votes})。"
                    )

    async def _initiate_proposal_confirmation(
        self,
        channel_id: int,
        guild_id: int,
        user_id: int,
        user_role_ids: set[int],
        expected_status: list[ProposalStatus],
        context: str,
        error_message: str,
        integrity_error_message: str,
        reason: str | None = None,
        check_24h: bool = False,
    ) -> Optional[ExecuteProposalResultDto]:
        """
        发起提案确认流程的通用私有方法。
        """
        session_dto: ConfirmationSessionDto | None = None
        message_id_placeholder = 0

        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                proposal = await uow.proposal.get_proposal_by_thread_id(channel_id)
                if not proposal:
                    raise ValueError("未找到关连的提案。")

                # 如果要求判断提案生命周期，校验提案创建是否已超过24小时
                if check_24h:
                    now = datetime.now(timezone.utc)
                    if now - proposal.created_at < timedelta(hours=24):
                        raise ValueError("提案讨论时间不足 24 小时，暂无法发起此操作。")

                # 帖子状态验证
                if proposal.status not in expected_status:
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
                    reason=reason,
                )
                session = await uow.confirmation_session.create_confirmation_session(
                    create_session_qo
                )
                session_dto = ConfirmationSessionDto.model_validate(session)

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
            await uow.confirmation_session.update_confirmation_session_message_id(
                session_id, message_id
            )
            await uow.commit()

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
                await uow.proposal.update_proposal_status_by_thread_id(
                    thread_id=announcement.discussion_thread_id,
                    status=ProposalStatus.EXECUTING,
                )
                await uow.commit()
        except Exception as e:
            logger.error(
                f"处理公示结束事件时发生错误 (帖子ID: {announcement.discussion_thread_id}): {e}",
                exc_info=True,
            )

    async def process_new_discussion_thread(self, thread: discord.Thread) -> None:
        """
        处理一个新发现的、未被记录的讨论区帖子<br>
        该方法会先判断帖子是提案还是异议，然后执行相应的处理
        """
        # 检查帖子是否由 Bot 自己创建
        # 如果是 Bot 创建的，说明是 Intake 模块流程自动生成的，数据库中已有记录，无需重复处理
        if self.bot.user and thread.owner_id == self.bot.user.id:
            logger.info(f"帖子 {thread.id} 由 Bot 创建 (Intake 流程)，跳过 Moderation 自动发现。")
            return

        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                # 检查它是否是一个已知的异议帖
                objection = await uow.objection.get_objection_by_thread_id(thread.id)
                if objection:
                    logger.debug(f"帖子 {thread.id} 是一个已知的异议帖，跳过处理")
                    return

                # 检查它是否已经是一个已知的提案帖
                proposal = await uow.proposal.get_proposal_by_thread_id(thread.id)
                if proposal:
                    logger.debug(f"提案 (帖子 ID: {thread.id}) 已存在，跳过处理")
                    return

            # 如果以上都不是，则认定为新提案，执行创建流程
            logger.info(f"发现新的提案帖: {thread.name} ({thread.id})。正在处理...")

            # 获取首楼内容和提案人信息
            raw_content = await StringUtils.extract_starter_content(thread)
            if not raw_content:
                logger.warning(f"无法获取帖子 {thread.id} 的首楼内容，中止提案创建。")
                return

            proposer_id = StringUtils.extract_proposer_id_from_content(raw_content)
            if not proposer_id:
                proposer_id = thread.owner_id

            clean_content = StringUtils.clean_proposal_content(raw_content)
            clean_title = StringUtils.clean_title(thread.name)

            # 在数据库中创建提案
            proposal_dto = None
            async with UnitOfWork(self.bot.db_handler) as uow:
                proposal = await uow.proposal.create_proposal(
                    thread.id, proposer_id, clean_title, clean_content
                )
                if proposal:
                    proposal_dto = ProposalDto.model_validate(proposal)
                await uow.commit()

            # 如果创建了 *新* 的提案，则更新UI并派发事件
            if proposal_dto:
                logger.info(f"已处理新提案 '{clean_title}' (帖子 ID: {thread.id})。")
                # 更新帖子外观（标签、标题前缀）
                thread_manager = ProposalThreadManager(self.bot.config)
                await thread_manager.update_status(thread, "discussion")
                # 派发事件，让 Voting cog 创建投票面板
                self.bot.dispatch(
                    "vote_session_created",
                    proposal_dto=proposal_dto,
                    options=[],
                    duration_hours=VoteDuration.PROPOSAL_DEFAULT,
                    anonymous=True,
                    realtime=True,
                    notify=True,
                    create_in_voting_channel=True,
                    notify_creation_role=True,
                    thread=thread,
                )

        except Exception as e:
            logger.error(
                f"处理新讨论帖 {thread.id} 时发生错误: {e}",
                exc_info=True,
            )

    async def mark_proposal_under_objection(self, thread_id: int) -> None:
        """
        将提案标记为“异议中”，并更新帖子外观
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            proposal = await uow.proposal.get_proposal_by_thread_id(thread_id)
            if not proposal:
                logger.warning(f"未找到与帖子 {thread_id} 关联的提案，跳过状态更新。")
                return

            if proposal.status == ProposalStatus.UNDER_OBJECTION:
                logger.debug(f"提案帖子 {thread_id} 已是异议中，跳过重复更新。")
                return

            proposal.status = ProposalStatus.UNDER_OBJECTION
            uow.session.add(proposal)
            await uow.commit()

        try:
            thread = await DiscordUtils.fetch_thread(self.bot, thread_id)
            if not isinstance(thread, discord.Thread):
                logger.warning(f"频道 {thread_id} 不是帖子类型，跳过外观同步。")
                return
            await self.thread_manager.update_status(thread, "under_objection")
        except Exception as e:
            logger.error(f"提案帖子 {thread_id} 状态已入库，但更新 Discord UI 失败: {e}", exc_info=True)
            return

        logger.info(f"提案帖子 {thread_id} 已更新为异议中。")

    async def clear_proposal_objection_status(self, thread_id: int) -> None:
        """
        （当异议被清空时）将提案标记为"讨论中"，并更新帖子外观
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            proposal = await uow.proposal.get_proposal_by_thread_id(thread_id)
            if not proposal:
                logger.warning(f"未找到与帖子 {thread_id} 关联的提案，跳过状态更新。")
                return

            if proposal.status != ProposalStatus.UNDER_OBJECTION:
                logger.debug(f"提案帖子 {thread_id} 当前不是异议中状态，无需恢复讨论中。")
                return

            proposal.status = ProposalStatus.DISCUSSION
            uow.session.add(proposal)
            await uow.commit()

        try:
            thread = await DiscordUtils.fetch_thread(self.bot, thread_id)
            if not isinstance(thread, discord.Thread):
                logger.warning(f"频道 {thread_id} 不是帖子类型，跳过外观同步。")
                return
            await self.thread_manager.update_status(thread, "discussion")
        except Exception as e:
            logger.error(f"提案帖子 {thread_id} 状态已入库，但更新 Discord UI 失败: {e}", exc_info=True)
            return

        logger.info(f"提案帖子 {thread_id} 的异议已清空，已恢复为讨论中。")

    async def proposal_status_change(
        self, proposal_id: int, new_status: ProposalStatus
    ) -> ProposalDto | None:
        """
        通用方法：处理提案状态变更的确认事件。
        """
        session_message_ids_to_refresh: list[int] = []

        # 更新提案状态；必要时清理异议选项
        async with UnitOfWork(self.bot.db_handler) as uow:
            proposal = await uow.proposal.get_proposal_by_id(proposal_id)
            if not proposal:
                logger.warning(
                    f"无法找到ID为 {proposal_id} 的提案，无法更新状态为 {new_status.name}。"
                )
                return None

            # 清理异议选项的条件：当前状态为“异议中”，且目标状态为“讨论中”
            needs_objection_cleanup = (
                proposal.status == ProposalStatus.UNDER_OBJECTION
                and new_status == ProposalStatus.DISCUSSION
            )

            if needs_objection_cleanup:
                sessions = await uow.vote_session.get_all_sessions_in_thread_with_details(
                    proposal.discussion_thread_id
                )
                session_ids = [s.id for s in sessions if s.id is not None]
                objection_options = await uow.vote_option.get_options_by_session_ids(session_ids, 1)

                for option in objection_options:
                    assert option.id is not None
                    await uow.vote_option.delete_option(option.id)

                session_message_ids_to_refresh = [
                    s.context_message_id for s in sessions if s.context_message_id is not None
                ]

            proposal.status = new_status
            result = ProposalDto.model_validate(proposal)
            uow.session.add(proposal)
            await uow.commit()

        # 刷新受影响的投票详情面板（存在时）
        for message_id in session_message_ids_to_refresh:
            try:
                async with UnitOfWork(self.bot.db_handler) as uow:
                    vote_session = await uow.vote_session.get_vote_session_with_details(message_id)
                    if not vote_session:
                        logger.warning(f"找不到与消息 ID {message_id} 关联的投票会话，跳过面板刷新。")
                        continue

                    vote_options = None
                    if vote_session.id:
                        vote_options = await uow.vote_option.get_vote_options(vote_session.id)

                    vote_details = VoteSessionService.get_vote_details_dto(vote_session, vote_options)

                self.bot.dispatch("vote_details_updated", vote_details)
            except Exception as e:
                logger.error(f"刷新投票面板失败 message_id={message_id}: {e}", exc_info=True)

        return result
