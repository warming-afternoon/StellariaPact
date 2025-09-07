import asyncio
import logging
from typing import TYPE_CHECKING, Literal

import discord
from discord.ext import commands

from StellariaPact.cogs.Moderation.qo.ObjectionSupportQo import \
    ObjectionSupportQo

from ....cogs.Moderation.dto.CollectionExpiredResultDto import \
    CollectionExpiredResultDto
from ....cogs.Moderation.dto.ConfirmationCompletedDto import \
    ConfirmationSessionDto
from ....cogs.Moderation.dto.HandleSupportObjectionResultDto import \
    HandleSupportObjectionResultDto
from ....cogs.Moderation.dto.ProposalDto import ProposalDto
from ....cogs.Moderation.qo.BuildAdminReviewEmbedQo import \
    BuildAdminReviewEmbedQo
from ....cogs.Moderation.qo.BuildProposalFrozenEmbedQo import \
    BuildProposalFrozenEmbedQo
from ....cogs.Moderation.qo.EditObjectionReasonQo import EditObjectionReasonQo
from ....cogs.Moderation.views.ModerationEmbedBuilder import \
    ModerationEmbedBuilder
from ....cogs.Voting.dto.VoteSessionDto import VoteSessionDto
from ....cogs.Voting.dto.VoteStatusDto import VoteStatusDto
from ....share.DiscordUtils import DiscordUtils
from ....share.enums.ProposalStatus import ProposalStatus
from ....share.StringUtils import StringUtils
from ....share.UnitOfWork import UnitOfWork
from ..ModerationLogic import ModerationLogic
from ..thread_manager import ProposalThreadManager

if TYPE_CHECKING:
    from ....share.StellariaPactBot import StellariaPactBot


logger = logging.getLogger(__name__)


class ModerationListener(commands.Cog):
    """
    专门用于监听与议事管理模块相关的内部和外部事件。
    """

    def __init__(self, bot: "StellariaPactBot"):
        self.bot = bot
        self.logic = ModerationLogic(bot)
        self.thread_manager = ProposalThreadManager(bot.config)

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        """
        监听新帖子的创建，如果是提案，则负责创建提案实体、更新UI并派发事件。
        """
        await asyncio.sleep(0.5)
        # 检查是否为提案讨论帖
        discussion_channel_id_str = self.bot.config.get("channels", {}).get("discussion")
        if not discussion_channel_id_str or thread.parent_id != int(discussion_channel_id_str):
            return

        # 检查它是否是异议帖，如果是，则忽略
        async with UnitOfWork(self.bot.db_handler) as uow:
            objection_dto = await uow.moderation.get_objection_by_thread_id(thread.id)
            if objection_dto:
                logger.debug(f"帖子 {thread.id} 是异议帖，不由 ModerationListener 处理。")
                return

        logger.debug(f"ModerationListener 捕获到新的提案帖: {thread.id}")

        try:
            # 1. 获取发起人并创建提案
            starter_message = thread.starter_message
            if not starter_message:
                starter_message = await thread.fetch_message(thread.id)
            if not starter_message:
                logger.warning(f"无法获取帖子 {thread.id} 的启动消息，无法创建提案。")
                return
            
            # 2. 更新帖子状态
            await self.thread_manager.update_status(thread, "discussion")

            proposer_id = starter_message.author.id
            clean_title = StringUtils.clean_title(thread.name)

            async with UnitOfWork(self.bot.db_handler) as uow:
                proposal_dto = await uow.moderation.create_proposal(
                    thread.id, proposer_id, clean_title
                )
                await uow.commit()

            # 3. 如果成功创建了新的提案，则派发事件
            if proposal_dto:
                self.bot.dispatch("proposal_created", proposal_dto)
            else:
                logger.debug(f"提案 {thread.id} 已存在，不派发事件。")

        except Exception as e:
            logger.error(
                f"ModerationListener 在处理帖子创建事件时发生错误 (ID: {thread.id}): {e}",
                exc_info=True,
            )

    @commands.Cog.listener()
    async def on_objection_vote_finished(
        self, session_dto: VoteSessionDto, result_dto: VoteStatusDto
    ):
        """
        监听由 VoteCloser 分派的异议投票结束事件。
        """
        logger.info(
            f"接收到异议投票结束事件，异议ID: {session_dto.objectionId}，分派到 logic 层处理。"
        )
        try:
            # 调用 Logic 层处理数据库事务
            final_result = await self.logic.handle_objection_vote_finished(session_dto, result_dto)

            if not final_result:
                logger.warning(
                    f"处理异议投票结束事件 (异议ID: {session_dto.objectionId}) 未返回有效结果。"
                )
                return

            # 更新公示频道的投票面板
            await self._update_publicity_panel(final_result)

            # 处理帖子状态变更
            await self._handle_thread_status_after_vote(final_result)

        except Exception as e:
            logger.error(f"在 on_objection_vote_finished 中发生意外错误: {e}", exc_info=True)

    @commands.Cog.listener("on_objection_collection_expired")
    async def on_objection_collection_expired(
        self, session_dto: VoteSessionDto, result_dto: VoteStatusDto
    ):
        """
        监听由 VoteCloser 分派的异议支持票收集到期事件。
        """
        logger.info(
            f"接收到异议支持票收集到期事件，异议ID: {session_dto.objectionId}，分派到 logic 层处理。"
        )
        try:
            final_result = await self.logic.handle_objection_collection_expired(
                session_dto, result_dto
            )

            if not final_result:
                logger.warning(
                    f"处理异议支持票收集到期事件 (异议ID: {session_dto.objectionId}) 未返回有效结果。"
                )
                return

            # 更新公示频道的投票面板
            await self._update_publicity_panel_for_collection_expired(final_result)

        except Exception as e:
            logger.error(f"在 on_objection_collection_expired 中发生意外错误: {e}", exc_info=True)

    @commands.Cog.listener("on_announcement_finished")
    async def on_announcement_finished(self, announcement):
        """
        监听由 Notification cog 分派的公示结束事件。
        """
        logger.info(
            f"接收到公示结束事件，帖子ID: {announcement.discussionThreadId}，分派到 logic 层处理。"
        )
        await self.logic.handle_announcement_finished(announcement)

    @commands.Cog.listener()
    async def on_objection_goal_reached(self, result_dto: HandleSupportObjectionResultDto):
        """
        监听异议支持票数达到目标的事件，创建异议帖。
        """
        logger.info(f"异议 {result_dto.objection_id} 已达到目标票数，准备创建异议帖。")

        try:
            # 获取必要的配置和数据
            discussion_channel_id_str = self.bot.config.get("channels", {}).get("discussion")
            if not discussion_channel_id_str:
                raise RuntimeError("未配置提案讨论频道 (discussion)。")

            discussion_channel = await DiscordUtils.fetch_channel(
                self.bot, int(discussion_channel_id_str)
            )
            if not isinstance(discussion_channel, discord.ForumChannel):
                raise RuntimeError("提案讨论频道必须是论坛频道。")

            #  构建帖子内容
            thread_name = f"异议 - {result_dto.proposal_title}"
            content = (
                f"**关联提案**: <#{result_dto.proposal_discussion_thread_id}>\n"
                f"**异议发起人**: <@{result_dto.objector_id}>\n\n"
                f"**理由**:\n{result_dto.objection_reason}\n\n"
                f"现在，请就此异议进行讨论和投票。"
            )

            # 创建异议帖
            thread_with_message = await self.bot.api_scheduler.submit(
                discussion_channel.create_thread(name=thread_name, content=content),
                priority=3,
            )
            objection_thread = thread_with_message[0]
            logger.info(
                f"成功为异议 {result_dto.objection_id} 创建了异议帖: {objection_thread.id}"
            )

            # 更新数据库和原提案
            assert result_dto.objection_id is not None, "Objection ID is required"
            assert result_dto.proposal_discussion_thread_id is not None, (
                "Original proposal thread ID is required"
            )

            objection_details_dto = await self.logic.handle_objection_thread_creation(
                objection_id=result_dto.objection_id,
                objection_thread_id=objection_thread.id,
                original_proposal_thread_id=result_dto.proposal_discussion_thread_id,
            )

            # 派发事件，通知 Voting 模块创建投票面板
            if objection_details_dto:
                self.bot.dispatch(
                    "objection_thread_created", objection_thread, objection_details_dto
                )
            else:
                logger.warning(
                    f"未能获取到 ObjectionDetailsDto，无法为异议帖 {objection_thread.id} 派发创建投票事件。"
                )

            # 更新原提案帖的标签和标题
            original_thread = await DiscordUtils.fetch_thread(
                self.bot, result_dto.proposal_discussion_thread_id
            )
            if original_thread:
                # 在原提案帖发送通知
                embed_qo = BuildProposalFrozenEmbedQo(
                    objection_thread_jump_url=objection_thread.jump_url
                )
                notification_embed = ModerationEmbedBuilder.build_proposal_frozen_embed(embed_qo)
                await self.bot.api_scheduler.submit(
                    original_thread.send(embed=notification_embed), priority=4
                )
                
                await self.thread_manager.update_status(original_thread, "frozen")

        except (RuntimeError, ValueError) as e:
            logger.error(f"处理 on_objection_goal_reached 事件时出错: {e}")
        except Exception as e:
            logger.error(f"处理 on_objection_goal_reached 事件时发生意外错误: {e}", exc_info=True)

    @commands.Cog.listener("on_edit_objection_reason_submitted")
    async def on_edit_objection_reason_submitted(self, qo: EditObjectionReasonQo):
        """
        监听来自 EditObjectionReasonModal 的事件，处理理由更新的完整流程。
        """
        interaction = qo.interaction
        try:
            # 调用 Logic 层处理业务逻辑和数据库操作
            result_dto = await self.logic.handle_update_objection_reason(qo)

            # 检查操作是否成功
            if not result_dto.success:
                await self.bot.api_scheduler.submit(
                    interaction.followup.send(result_dto.message, ephemeral=True), 1
                )
                return

            # 更新审核帖子中的 Embed
            if result_dto.review_thread_id:
                await self._update_review_embed(result_dto)

            # 向用户发送成功反馈
            await self.bot.api_scheduler.submit(
                interaction.followup.send(result_dto.message, ephemeral=True), 1
            )

        except Exception as e:
            logger.error(
                f"处理 on_edit_objection_reason_submitted 事件时发生未知错误: {e}",
                exc_info=True,
            )
            await self.bot.api_scheduler.submit(
                interaction.followup.send("更新理由时发生未知错误。", ephemeral=True), 1
            )

    # --- 私有方法 ---

    async def _update_review_embed(self, dto):
        """根据更新后的数据，找到并更新审核帖子中的 embed"""
        if not self.bot.user:
            logger.error("机器人尚未登录，无法更新审核帖子。")
            return

        review_thread = await DiscordUtils.fetch_thread(self.bot, dto.review_thread_id)
        if not review_thread:
            logger.warning(f"无法找到审核帖子 {dto.review_thread_id}，跳过 Embed 更新。")
            return

        try:
            # 假设需要更新的消息是帖子的第一条消息
            history = review_thread.history(limit=1, oldest_first=True)
            original_message = await history.__anext__()

            if not original_message:
                logger.warning(f"审核帖子 {dto.review_thread_id} 中没有消息，无法更新。")
                return

            # 构建新的 Embed
            embed_qo = BuildAdminReviewEmbedQo(
                guild_id=dto.guild_id,
                proposal_id=dto.proposal_id,
                proposal_title=dto.proposal_title,
                proposal_thread_id=dto.proposal_thread_id,
                objection_id=dto.objection_id,
                objector_id=dto.objector_id,
                objection_reason=dto.new_reason,
            )
            new_embed = ModerationEmbedBuilder.build_admin_review_embed(embed_qo, self.bot.user)

            # 编辑消息
            await self.bot.api_scheduler.submit(original_message.edit(embed=new_embed), priority=3)
            logger.info(f"成功更新了审核帖子 {dto.review_thread_id} 中的异议理由。")

        except StopAsyncIteration:
            logger.warning(f"审核帖子 {dto.review_thread_id} 为空，无法找到消息进行更新。")
        except Exception as e:
            logger.error(
                f"更新审核帖子 {dto.review_thread_id} 的 Embed 时出错: {e}", exc_info=True
            )


    async def _update_publicity_panel(self, result):
        """更新公示频道中的原始投票消息"""
        if not self.bot.user:
            logger.error("机器人尚未登录，无法更新投票面板。")
            return

        channel = (
            await DiscordUtils.fetch_channel(self.bot, result.notification_channel_id)
            if result.notification_channel_id
            else None
        )
        if not isinstance(channel, discord.TextChannel):
            logger.error(f"无法找到ID为 {result.notification_channel_id} 的文本频道。")
            return

        embed = ModerationEmbedBuilder.build_vote_result_embed(result.embed_qo, self.bot.user)

        if result.original_vote_message_id:
            try:
                message = await channel.fetch_message(result.original_vote_message_id)
                await self.bot.api_scheduler.submit(
                    message.edit(embed=embed, view=None), priority=5
                )
            except discord.NotFound:
                logger.warning(
                    f"无法找到原始投票消息 {result.original_vote_message_id}，将发送新消息。"
                )
                await self.bot.api_scheduler.submit(channel.send(embed=embed), priority=5)
            except Exception as e:
                logger.error(
                    f"更新原始投票消息 {result.original_vote_message_id} 时出错: {e}",
                    exc_info=True,
                )
        else:
            await self.bot.api_scheduler.submit(channel.send(embed=embed), priority=5)

    async def _update_publicity_panel_for_collection_expired(
        self, result: CollectionExpiredResultDto
    ):
        """更新公示频道中的原始投票消息（收集到期场景）"""
        if not self.bot.user:
            logger.error("机器人尚未登录，无法更新投票面板。")
            return

        channel = (
            await DiscordUtils.fetch_channel(self.bot, result.notification_channel_id)
            if result.notification_channel_id
            else None
        )
        if not isinstance(channel, discord.TextChannel):
            logger.error(f"无法找到ID为 {result.notification_channel_id} 的文本频道。")
            return

        embed = ModerationEmbedBuilder.build_collection_expired_embed(result.embed_qo)

        if result.original_vote_message_id:
            try:
                message = await channel.fetch_message(result.original_vote_message_id)
                await self.bot.api_scheduler.submit(
                    message.edit(embed=embed, view=None), priority=5
                )
            except discord.NotFound:
                logger.warning(
                    f"无法找到原始投票消息 {result.original_vote_message_id}，将发送新消息。"
                )
                await self.bot.api_scheduler.submit(channel.send(embed=embed), priority=5)
            except Exception as e:
                logger.error(
                    f"更新原始投票消息 {result.original_vote_message_id} 时出错: {e}",
                    exc_info=True,
                )
        else:
            await self.bot.api_scheduler.submit(channel.send(embed=embed), priority=5)

    async def _handle_thread_status_after_vote(self, result):
        """根据投票结果处理原提案和异议帖的状态"""
        original_thread = await DiscordUtils.fetch_thread(
            self.bot, result.original_proposal_thread_id
        )
        objection_thread = (
            await DiscordUtils.fetch_thread(self.bot, result.objection_thread_id)
            if result.objection_thread_id
            else None
        )

        if not original_thread:
            logger.error(f"找不到原提案帖 {result.original_proposal_thread_id}，无法更新状态。")
            return

        # 类型守卫，确保父频道是论坛
        if not isinstance(original_thread.parent, discord.ForumChannel):
            logger.warning(f"帖子 {original_thread.id} 的父频道不是论坛，无法修改标签。")
            return

        if not self.bot.user:
            logger.error("机器人尚未登录，无法发送结果通知。")
            return

        # 发送所有通知
        await self._send_paginated_vote_results(original_thread, result)
        if objection_thread:
            await self._send_paginated_vote_results(objection_thread, result)

        # 根据投票结果，执行后续的帖子状态变更
        if result.is_passed:
            # 异议通过 -> 原提案被否决
            if original_thread:
                await self.thread_manager.update_status(original_thread, "rejected")
        else:
            # 异议失败 -> 原提案解冻
            if original_thread:
                await self.thread_manager.update_status(original_thread, "discussion")
            # 将异议帖标记为否决并归档
            if objection_thread:
                await self.thread_manager.update_status(objection_thread, "rejected")

    async def _send_paginated_vote_results(
        self, channel: discord.TextChannel | discord.Thread, result
    ):
        """根据投票结果，发送主结果面板和分页的投票人列表。"""
        if not self.bot.user:
            logger.error("机器人尚未登录，无法发送结果通知。")
            return

        # 发送主结果 Embed
        main_embed = ModerationEmbedBuilder.build_vote_result_embed(result.embed_qo, self.bot.user)
        await self.bot.api_scheduler.submit(channel.send(embed=main_embed), priority=3)

        # # 准备并发送分页的投票人列表
        # voter_embeds = []
        # if result.approve_voter_ids:
        #     voter_embeds.extend(
        #         ModerationEmbedBuilder.build_voter_list_embeds(
        #             "✅ 赞成方", result.approve_voter_ids, discord.Color.green()
        #         )
        #     )
        # if result.reject_voter_ids:
        #     voter_embeds.extend(
        #         ModerationEmbedBuilder.build_voter_list_embeds(
        #             "❌ 反对方", result.reject_voter_ids, discord.Color.red()
        #         )
        #     )

        # # Discord 一次最多发送 10 个 embeds
        # for i in range(0, len(voter_embeds), 10):
        #     chunk = voter_embeds[i : i + 10]
        #     await self.bot.api_scheduler.submit(channel.send(embeds=chunk), priority=3)

    @commands.Cog.listener("on_objection_creation_vote_cast")
    async def on_objection_creation_vote_cast(
        self, interaction: discord.Interaction, choice: Literal["support", "withdraw"]
    ):
        """
        监听来自 ObjectionCreationVoteView 的投票事件。
        """
        if not interaction.message:
            logger.warning("on_objection_creation_vote_cast 收到一个没有消息的交互。")
            # 可以在这里发送一个临时的错误消息，但通常 view 层已经处理了，所以只记录日志
            return

        logger.info(
            (
                "接收到异议创建投票事件: "
                f"user={interaction.user.id}, choice={choice}, message={interaction.message.id}"
            )
        )

        try:
            # 准备QO并调用Logic层
            qo = ObjectionSupportQo(
                userId=interaction.user.id,
                messageId=interaction.message.id,
                action=choice,
            )

            if choice == "support":
                result_dto = await self.logic.handle_support_objection(qo)
            else:
                result_dto = await self.logic.handle_withdraw_support(qo)

            self.bot.dispatch("update_objection_vote_panel", interaction.message, result_dto)

            # 根据返回的DTO提供精确的用户反馈
            feedback_messages = {
                "supported": "成功支持该异议！",
                "withdrew": "成功撤回支持。",
                "already_supported": "您已经支持过此异议了。",
                "not_supported": "您尚未支持此异议，无法撤回。",
            }
            feedback_message = feedback_messages.get(result_dto.user_action_result, "操作已处理。")
            await self.bot.api_scheduler.submit(
                interaction.followup.send(feedback_message, ephemeral=True), 1
            )

        except (ValueError, RuntimeError) as e:
            logger.warning(f"处理异议创建投票时发生错误: {e}")
            await self.bot.api_scheduler.submit(
                interaction.followup.send(f"操作失败: {e}", ephemeral=True), 1
            )
        except Exception as e:
            logger.error(f"处理异议创建投票时发生未知错误: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send("发生未知错误，请联系技术员。", ephemeral=True), 1
            )

    @commands.Cog.listener()
    async def on_confirmation_completed(self, session: ConfirmationSessionDto):
        logger.debug(f"接收到确认完成事件，上下文: {session.context}，目标ID: {session.targetId}")

        try:
            proposal_dto: ProposalDto | None = None
            target_status: ProposalStatus | None = None

            match session.context:
                case "proposal_execution":
                    proposal_dto = await self.logic.handle_proposal_execution_confirmed(
                        session.targetId
                    )
                    target_status = ProposalStatus.EXECUTING
                case "proposal_completion":
                    proposal_dto = await self.logic.handle_proposal_completion_confirmed(
                        session.targetId
                    )
                    target_status = ProposalStatus.FINISHED
                case _:
                    logger.warning(f"未知的确认上下文: {session.context}")
                    return

            if proposal_dto and target_status and proposal_dto.discussionThreadId:
                await self._update_thread_status_after_confirmation(
                    proposal_dto.discussionThreadId,
                    proposal_dto.title,
                    target_status,
                )
            else:
                logger.warning(
                    f"从 logic 层返回的 proposal_dto 为空，无法更新帖子状态。Proposal ID: {session.targetId}"
                )

        except Exception as e:
            logger.error(f"处理确认完成事件时出错: {e}", exc_info=True)

    async def _update_thread_status_after_confirmation(
        self, thread_id: int, title: str, target_status: ProposalStatus
    ):
        """ 根据确认结果更新帖子状态 """
        try:
            thread = await DiscordUtils.fetch_thread(self.bot, thread_id)
            if not thread:
                logger.warning(f"无法找到ID为 {thread_id} 的帖子，无法更新状态。")
                return

            # 将枚举映射到状态关键字
            status_key_map = {
                ProposalStatus.EXECUTING: "executing",
                ProposalStatus.FINISHED: "finished",
            }
            status_key = status_key_map.get(target_status)

            if status_key:
                await self.thread_manager.update_status(thread, status_key)
            else:
                logger.warning(f"未知的提案状态: {target_status}，无法更新帖子。")

        except Exception as e:
            logger.error(f"更新帖子 {thread_id} 状态时发生未知错误: {e}", exc_info=True)
