
import logging
from typing import Optional

import discord
from sqlalchemy.exc import IntegrityError

from ....cogs.Voting.dto.VoteSessionDto import VoteSessionDto
from ....cogs.Voting.dto.VoteStatusDto import VoteStatusDto
from ....cogs.Voting.qo.CreateVoteSessionQo import CreateVoteSessionQo
from ....models.Announcement import Announcement
from ....models.Objection import Objection
from ....models.Proposal import Proposal
from ....share.enums.ObjectionStatus import ObjectionStatus
from ....share.enums.ProposalStatus import ProposalStatus
from ....share.StellariaPactBot import StellariaPactBot
from ....share.UnitOfWork import UnitOfWork
from ..dto.ConfirmationSessionDto import ConfirmationSessionDto
from ..dto.ExecuteProposalResultDto import ExecuteProposalResultDto
from ..dto.ObjectionInitiationDto import ObjectionInitiationDto
from ..dto.RaiseObjectionResultDto import RaiseObjectionResultDto
from ..qo.BuildAdminReviewEmbedQo import BuildAdminReviewEmbedQo
from ..qo.BuildFormalVoteEmbedQo import BuildFormalVoteEmbedQo
from ..qo.BuildVoteResultEmbedQo import BuildVoteResultEmbedQo
from ..qo.CreateConfirmationSessionQo import CreateConfirmationSessionQo
from ..qo.CreateObjectionQo import CreateObjectionQo
from ..views.ModerationEmbedBuilder import ModerationEmbedBuilder
from ..views.ObjectionFormalVoteView import ObjectionFormalVoteView

logger = logging.getLogger(__name__)


class ModerationLogic:
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
        处理发起异议的完整业务流程。
        """
        event_dto: Optional[ObjectionInitiationDto] = None
        is_first_objection = False
        message: str = ""

        async with UnitOfWork(self.bot.db_handler) as uow:
            proposal = await uow.moderation.get_proposal_by_thread_id(target_thread_id)
            if not proposal:
                raise ValueError("未在指定帖子中找到关连的提案。")

            if proposal.status not in [
                ProposalStatus.DISCUSSION,
                ProposalStatus.EXECUTING,
            ]:
                raise ValueError("只能对“讨论中”或“执行中”的提案发起异议。")

            assert proposal.id is not None
            existing_objections = await uow.moderation.get_objections_by_proposal_id(
                proposal.id
            )
            is_first_objection = not bool(existing_objections)

            required_votes = 5 if is_first_objection else 10
            initial_status = (
                ObjectionStatus.COLLECTING_VOTES
                if is_first_objection
                else ObjectionStatus.PENDING_REVIEW
            )

            qo = CreateObjectionQo(
                proposal_id=proposal.id,
                objector_id=user_id,
                reason=reason,
                required_votes=required_votes,
                status=initial_status,
            )
            objection = await uow.moderation.create_objection(qo)
            await uow.flush([objection])  # Flush to get the auto-generated ID

            # 创建事件 DTO
            event_dto = ObjectionInitiationDto(
                objection_id=objection.id,  # type: ignore
                objector_id=objection.objector_id,
                objection_reason=objection.reason,
                required_votes=objection.requiredVotes,
                proposal_id=proposal.id,
                proposal_title=proposal.title,
                proposal_thread_id=proposal.discussionThreadId,
            )
            await uow.commit()

        # 分派事件
        if event_dto:
            if is_first_objection:
                logger.debug(f"准备分派事件 'on_objection_creation_vote_initiation' for objection {event_dto.objection_id}")
                self.bot.dispatch("on_objection_creation_vote_initiation", event_dto)
                logger.debug(f"事件 'on_objection_creation_vote_initiation' 已分派。")
                message = "首次异议已成功发起！将在公示频道开启异议产生票收集。"
            else:
                self.bot.dispatch("objection_admin_review_initiation", event_dto)
                message = "异议已成功发起！由于该提案已有其他异议，本次异议需要先由管理员审核。"

        return RaiseObjectionResultDto(
            message=message,
            is_first_objection=is_first_objection,
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
                    message_id=message_id_placeholder, # 稍后更新
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
            await uow.moderation.update_confirmation_session_message_id(
                session_id, message_id
            )
            await uow.commit()

    async def handle_objection_creation_vote_initiation(
        self, event_dto: ObjectionInitiationDto, message_sender
    ) -> None:
        """
        处理“异议产生票”发起事件的完整业务流程。
        包括构建UI、发送消息、创建数据库记录。
        """
        try:
            # 1. 获取必要信息
            guild_id = self.bot.config.get("guild_id")
            if not guild_id:
                raise ValueError("未在 config.json 中配置 'guild_id'。")

            objector = await self.bot.fetch_user(event_dto.objector_id)
            objector_name = objector.display_name if objector else f"用户 {event_dto.objector_id}"
            objector_avatar = objector.avatar.url if objector and objector.avatar else None

            # 2. 构建 Embed
            proposal_url = f"https://discord.com/channels/{guild_id}/{event_dto.proposal_thread_id}"
            embed = discord.Embed(
                title="异议产生票收集中",
                description=f"对提案 **[{event_dto.proposal_title}]({proposal_url})** 的一项异议需要收集足够的支持票以进入正式投票阶段。",
                color=discord.Color.yellow(),
            )
            embed.add_field(
                name="异议理由", value=f">>> {event_dto.objection_reason}", inline=False
            )
            embed.add_field(
                name="所需票数", value=str(event_dto.required_votes), inline=True
            )
            embed.add_field(
                name="当前支持", value=f"0 / {event_dto.required_votes}", inline=True
            )
            embed.set_footer(text=f"由 {objector_name} 发起", icon_url=objector_avatar)

            # 3. 调用传入的函数发送消息
            # 注意：View 的构建被保留在 Cog 层，因为 View 自身可能需要 bot 实例和其它上下文
            message_id = await message_sender(embed)
            if not message_id:
                logger.error("消息发送函数未能返回有效的 message_id。")
                return

            # 4. 创建数据库记录
            async with UnitOfWork(self.bot.db_handler) as uow:
                qo = CreateVoteSessionQo(
                    thread_id=event_dto.proposal_thread_id,
                    objection_id=event_dto.objection_id,
                    context_message_id=message_id,
                    realtime=True,
                    anonymous=False,
                )
                await uow.voting.create_vote_session(qo)
                await uow.commit()

            logger.info(f"已为异议 {event_dto.objection_id} 成功发起产生票并创建了投票会话。")

        except Exception as e:
            logger.exception(f"为异议 {event_dto.objection_id} 发起产生票时发生错误: {e}")

    async def handle_objection_admin_review_initiation(
        self, event_dto: ObjectionInitiationDto
    ) -> BuildAdminReviewEmbedQo:
        """
        处理非首次异议的管理员审核发起事件。
        """
        guild_id = self.bot.config.get("guild_id")
        if not guild_id:
            # 在这种情况下，抛出异常比记录错误更好，因为调用方需要知道操作失败了
            raise ValueError("未在 config.json 中配置 'guild_id'。")

        return BuildAdminReviewEmbedQo(
            objection_id=event_dto.objection_id,
            objector_id=event_dto.objector_id,
            objection_reason=event_dto.objection_reason,
            proposal_id=event_dto.proposal_id,
            proposal_title=event_dto.proposal_title,
            proposal_thread_id=event_dto.proposal_thread_id,
            guild_id=int(guild_id),
        )

    async def handle_objection_formal_vote_initiation(
        self, objection: Objection, proposal: Proposal
    ):
        """
        处理正式异议投票发起事件的业务逻辑。
        """
        channel_id = self.bot.config.get("channels", {}).get("objection_publicity")
        if not channel_id:
            logger.error("未在 config.json 中配置 'objection_publicity' 频道ID。")
            return

        channel = self.bot.get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            logger.error(f"无法找到ID为 {channel_id} 的文本频道，或类型不正确。")
            return

        if not self.bot.user:
            logger.error("机器人尚未登录，无法创建投票。")
            return

        # 构建投票Embed
        guild_id = self.bot.config.get("guild_id")
        if not guild_id:
            logger.error("未在 config.json 中配置 'guild_id'。")
            return
        assert objection.id is not None, "Objection ID cannot be None for formal vote embed"
        qo = BuildFormalVoteEmbedQo(
            proposal_title=proposal.title,
            proposal_thread_url=f"https://discord.com/channels/{guild_id}/{proposal.discussionThreadId}",
            objection_id=objection.id,
            objector_id=objection.objector_id,
            objection_reason=objection.reason,
        )
        embed = ModerationEmbedBuilder.build_formal_vote_embed(qo, self.bot.user)

        # 创建投票视图
        assert objection.id is not None
        view = ObjectionFormalVoteView(self.bot, objection.id)

        # 发送消息并创建投票会话
        try:
            message = await self.bot.api_scheduler.submit(
                channel.send(embed=embed, view=view), priority=5
            )
            async with UnitOfWork(self.bot.db_handler) as uow:
                assert objection.id is not None, "Objection ID cannot be None here"
                # 注意：这里的 thread_id 仍然是提案的帖子ID，用于上下文关联
                vote_qo = CreateVoteSessionQo(
                    thread_id=proposal.discussionThreadId,
                    objection_id=objection.id,
                    context_message_id=message.id,
                    realtime=True,
                    anonymous=False,
                    # end_time 可以根据需要设置，例如72小时后
                )
                await uow.voting.create_vote_session(vote_qo)
                await uow.commit()
            logger.info(f"已为异议 {objection.id} 在频道 {channel.id} 中创建了正式投票面板。")
        except Exception as e:
            logger.exception(f"为异议 {objection.id} 创建正式投票面板时发生错误: {e}")

    async def handle_objection_vote_finished(
        self, session_dto: VoteSessionDto, result_dto: VoteStatusDto
    ):
        """
        处理异议投票结束事件的业务逻辑。
        """
        objection_id = session_dto.objectionId
        if objection_id is None:
            logger.warning(f"投票会话 {session_dto.id} 结束，但没有关联的异议ID。")
            return

        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                # 1. 判断投票结果
                is_passed = result_dto.approveVotes > result_dto.rejectVotes
                new_status = (
                    ObjectionStatus.PASSED if is_passed else ObjectionStatus.REJECTED
                )

                # 2. 更新异议状态
                await uow.moderation.update_objection_status(objection_id, new_status)
                objection = await uow.moderation.get_objection_by_id(objection_id)
                proposal = (
                    await uow.moderation.get_proposal_by_id(objection.proposalId)
                    if objection
                    else None
                )
                await uow.commit()

            # 3. 发送通知
            if not objection or not proposal:
                logger.error(f"无法为已结束的异议 {objection_id} 找到完整的上下文信息。")
                return

            publicity_channel_id = self.bot.config.get("channels", {}).get(
                "objection_publicity"
            )
            publicity_channel = (
                self.bot.get_channel(int(publicity_channel_id))
                if publicity_channel_id
                else None
            )

            if not self.bot.user:
                logger.error("机器人尚未登录，无法创建结果通知。")
                return

            assert objection.id is not None, "Objection ID cannot be None for result embed"
            guild_id = self.bot.config.get("guild_id")
            if not guild_id:
                logger.error("未在 config.json 中配置 'guild_id'。")
                return
                
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
            embed = ModerationEmbedBuilder.build_vote_result_embed(
                result_qo, self.bot.user
            )

            if isinstance(publicity_channel, discord.TextChannel) and session_dto.contextMessageId:
                try:
                    original_message = await publicity_channel.fetch_message(
                        session_dto.contextMessageId
                    )
                    await self.bot.api_scheduler.submit(
                        original_message.edit(embed=embed, view=None), priority=5
                    )
                except discord.NotFound:
                    logger.warning(
                        f"无法找到原始投票消息 {session_dto.contextMessageId}，将发送新消息。"
                    )
                    await self.bot.api_scheduler.submit(
                        publicity_channel.send(embed=embed), priority=5
                    )
                except Exception as e:
                    logger.error(f"更新原始投票消息时出错: {e}", exc_info=True)
                    await self.bot.api_scheduler.submit(
                        publicity_channel.send(embed=embed), priority=5
                    )
            elif isinstance(publicity_channel, discord.TextChannel):
                await self.bot.api_scheduler.submit(
                    publicity_channel.send(embed=embed), priority=5
                )

        except Exception as e:
            logger.exception(f"处理异议投票结束事件 (异议ID: {objection_id}) 时发生错误: {e}")

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