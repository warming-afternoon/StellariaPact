import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, Literal, Optional

import discord
from discord.ext import commands, tasks
from sqlalchemy import select, update

from StellariaPact.cogs.Moderation.dto import SubsequentObjectionDto
from StellariaPact.cogs.Moderation.ModerationLogic import ModerationLogic
from StellariaPact.cogs.Moderation.qo import (
    BuildAdminReviewEmbedQo,
    BuildProposalFrozenEmbedQo,
    EditObjectionReasonQo,
    ObjectionSupportQo,
)
from StellariaPact.cogs.Moderation.thread_manager import ProposalThreadManager
from StellariaPact.cogs.Moderation.views.ModerationEmbedBuilder import ModerationEmbedBuilder
from StellariaPact.cogs.Moderation.views.ObjectionManageView import ObjectionManageView
from StellariaPact.cogs.Moderation.views.ObjectionModal import ObjectionModal
from StellariaPact.dto import (
    ConfirmationSessionDto,
    HandleSupportObjectionResultDto,
    ObjectionVotePanelDto,
    ProposalDto,
)
from StellariaPact.models import UserActivity
from StellariaPact.share import DiscordUtils, StringUtils, UnitOfWork, safeDefer
from StellariaPact.share.enums import ProposalStatus

if TYPE_CHECKING:
    from StellariaPact.share.StellariaPactBot import StellariaPactBot


logger = logging.getLogger(__name__)


class ModerationListener(commands.Cog):
    """
    监听与议事管理模块相关的内部事件
    """

    def __init__(self, bot: "StellariaPactBot"):
        self.bot = bot
        self.logic = ModerationLogic(bot)
        self.thread_manager = ProposalThreadManager(bot.config)
        # 缓存结构: {thread_id: {user_id: mute_end_time}}
        self.active_mutes: Dict[int, Dict[int, datetime]] = {}
        self.clear_expired_mutes.start()

    def cog_unload(self):
        self.clear_expired_mutes.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        await self._load_active_mutes_into_cache()

    async def _load_active_mutes_into_cache(self):
        """从数据库加载所有当前有效的禁言记录到内存缓存中"""
        logger.info("正在加载有效的禁言记录到缓存...")
        self.active_mutes.clear()
        now = datetime.now(timezone.utc)
        async with UnitOfWork(self.bot.db_handler) as uow:
            statement = select(UserActivity).where(
                UserActivity.mute_end_time != None,  # type: ignore # noqa: E711
                UserActivity.mute_end_time > now,  # type: ignore
            )
            results = await uow.session.exec(statement)  # type: ignore
            for activity in results.all():
                if activity.context_thread_id not in self.active_mutes:
                    self.active_mutes[activity.context_thread_id] = {}
                if activity.mute_end_time:
                    self.active_mutes[activity.context_thread_id][activity.user_id] = (
                        activity.mute_end_time
                    )
        logger.info(
            f"成功加载 {sum(len(users) for users in self.active_mutes.values())} 条有效禁言记录。"
        )

    @tasks.loop(minutes=5)
    async def clear_expired_mutes(self):
        """每5分钟清理一次缓存和数据库中已过期的禁言记录"""
        logger.debug("正在清理已过期的禁言...")
        now = datetime.now(timezone.utc)
        expired_mutes_to_clear_from_db = []

        # 清理内存缓存
        for thread_id, users in list(self.active_mutes.items()):
            for user_id, end_time in list(users.items()):
                if now >= end_time:
                    del self.active_mutes[thread_id][user_id]
                    expired_mutes_to_clear_from_db.append((user_id, thread_id))
            if not self.active_mutes[thread_id]:
                del self.active_mutes[thread_id]

        # 清理数据库
        if expired_mutes_to_clear_from_db:
            async with UnitOfWork(self.bot.db_handler) as uow:
                for user_id, thread_id in expired_mutes_to_clear_from_db:
                    stmt = (
                        update(UserActivity)
                        .where(
                            UserActivity.user_id == user_id,
                            UserActivity.context_thread_id == thread_id,
                        )
                        .values(mute_end_time=None)
                    )
                    await uow.session.execute(stmt)
                await uow.commit()
            logger.info(f"已清理 {len(expired_mutes_to_clear_from_db)} 条过期的数据库禁言记录。")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        监听消息事件，检查并删除被禁言用户发送的消息
        """
        if (
            message.author.bot
            or not isinstance(message.channel, discord.Thread)
            or not message.guild
        ):
            return

        # 从缓存中快速检查是否被禁言
        thread_mutes = self.active_mutes.get(message.channel.id)
        if not thread_mutes:
            return

        mute_end_time = thread_mutes.get(message.author.id)
        if not mute_end_time:
            return

        # 检查禁言是否结束
        if datetime.now(timezone.utc) < mute_end_time:
            try:
                await message.delete()
                logger.info(
                    f"已删除用户 {message.author.id} 在帖子 {message.channel.id} "
                    "中的消息，原因：禁言中。"
                )
            except discord.Forbidden:
                logger.warning(f"缺少删除消息的权限，无法删除用户 {message.author.id} 的消息。")
            except discord.NotFound:
                pass  # 消息可能已被用户自己删除

    @commands.Cog.listener()
    async def on_thread_mute_updated(
        self, thread_id: int, user_id: int, mute_end_time: Optional[datetime]
    ):
        """监听禁言更新事件，并实时更新缓存"""
        if thread_id not in self.active_mutes:
            self.active_mutes[thread_id] = {}

        if mute_end_time and mute_end_time > datetime.now(timezone.utc):
            self.active_mutes[thread_id][user_id] = mute_end_time
            logger.debug(f"缓存已更新：用户 {user_id} 在帖子 {thread_id} 中被禁言。")
        elif user_id in self.active_mutes[thread_id]:
            # 如果 mute_end_time 为 None 或已过期，则从缓存中移除
            del self.active_mutes[thread_id][user_id]
            logger.debug(f"缓存已更新：用户 {user_id} 在帖子 {thread_id} 中的禁言被移除。")

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        """
        监听新帖子的创建，如果在提案讨论区，则委托给 ModerationLogic 处理
        """
        # 短暂休眠以等待帖子的启动消息被处理/缓存
        await asyncio.sleep(1)
        # 检查是否在提案讨论区
        discussion_channel_id_str = self.bot.config.get("channels", {}).get("discussion")
        if not discussion_channel_id_str or thread.parent_id != int(discussion_channel_id_str):
            return

        await self.logic.process_new_discussion_thread(thread)

    @commands.Cog.listener()
    async def on_objection_goal_reached(self, result_dto: HandleSupportObjectionResultDto):
        """
        监听异议支持票数达到目标的事件，创建异议帖
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
                    f"未能获取到 ObjectionDetailsDto，无法为异议帖 {objection_thread.id} "
                    "派发创建投票事件。"
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

    @commands.Cog.listener()
    async def on_objection_modal_submitted(
        self, interaction: discord.Interaction, proposal_link: str, reason: str
    ):
        """监听并处理从 ObjectionModal 提交的异议"""
        await safeDefer(interaction, ephemeral=True)

        try:
            # --- 阶段一: 创建数据库记录 ---
            target_thread_id = self._determine_target_thread_id(interaction, proposal_link)

            # 调用 Logic 层，它现在根据情况返回不同类型的 DTO
            if not interaction.guild:
                raise RuntimeError("交互不包含服务器信息。")
            result_dto = await self.logic.handle_raise_objection(
                user_id=interaction.user.id,
                target_thread_id=target_thread_id,
                reason=reason,
                guild_id=interaction.guild.id,
            )

            # --- 阶段二: 根据结果处理UI ---
            if isinstance(result_dto, ObjectionVotePanelDto):
                # 如果返回 DTO，说明是首次异议，派发事件让 Voting 模块创建面板
                assert isinstance(result_dto, ObjectionVotePanelDto)
                self.bot.dispatch("create_objection_vote_panel", result_dto, interaction)
                final_message = (
                    "异议已成功发起！\n由于为首次异议，将直接在公示频道开启异议产生票收集。"
                )
            elif isinstance(result_dto, SubsequentObjectionDto):
                # 如果返回 SubsequentObjectionDto，说明是后续异议，创建审核UI
                assert isinstance(result_dto, SubsequentObjectionDto)
                await self._handle_subsequent_objection_ui(interaction, result_dto)
                final_message = (
                    "异议已成功发起！\n由于该提案已有其他异议，本次异议需要先由管理员审核。"
                )
            else:
                # 兜底，理论上不应发生
                final_message = "操作已提交，但返回了未知的处理结果。"

            # --- 最终确认 ---
            await self.bot.api_scheduler.submit(
                interaction.followup.send(final_message, ephemeral=True), 1
            )

        except (ValueError, RuntimeError) as e:
            await self.bot.api_scheduler.submit(
                interaction.followup.send(str(e), ephemeral=True), 1
            )
        except Exception as e:
            logger.error(
                f"处理 'on_objection_modal_submitted' 事件时发生意外错误: {e}", exc_info=True
            )
            await self.bot.api_scheduler.submit(
                interaction.followup.send("发生未知错误，请联系技术员。", ephemeral=True), 1
            )

    @commands.Cog.listener()
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

    def _determine_target_thread_id(
        self, interaction: discord.Interaction, proposal_link: str
    ) -> int:
        """从交互上下文或链接中解析出目标帖子ID。

        Args:
            interaction (discord.Interaction): 当前的交互对象。
            proposal_link (str): 用户提供的提案链接。

        Raises:
            ValueError: 如果链接格式不正确或在没有链接的情况下不在帖子内使用。

        Returns:
            int: 解析出的帖子ID。
        """
        if proposal_link:
            thread_id = StringUtils.extract_thread_id_from_url(proposal_link)
            if not thread_id:
                raise ValueError("提供的链接格式不正确，无法识别帖子ID。")
            return thread_id
        elif isinstance(interaction.channel, discord.Thread):
            return interaction.channel.id
        else:
            raise ValueError("此命令必须在提案帖子内使用，或通过“提案链接”参数指定目标帖子。")

    async def _handle_subsequent_objection_ui(
        self, interaction: discord.Interaction, dto: SubsequentObjectionDto
    ):
        """处理后续异议的UI交互（发送审核面板）。"""
        # 获取频道
        channel_id_str = self.bot.config.get("channels", {}).get("objection_audit")
        if not channel_id_str:
            raise RuntimeError("审核频道未配置")
        if not self.bot.user:
            raise RuntimeError("机器人未登录")
        channel = await DiscordUtils.fetch_channel(self.bot, int(channel_id_str))

        if not isinstance(channel, discord.ForumChannel):
            raise RuntimeError(f"审核频道 (ID: {channel.id}) 不是一个论坛频道。")

        # 构建 Embed 和 View
        guild_id = self.bot.config.get("guild_id")
        if not guild_id:
            raise RuntimeError("服务器 ID (guild_id) 未配置")

        embed_qo = BuildAdminReviewEmbedQo(
            objection_id=dto.objection_id,
            objector_id=dto.objector_id,
            objection_reason=dto.objection_reason,
            proposal_id=dto.proposal_id,
            proposal_title=dto.proposal_title,
            proposal_thread_id=dto.proposal_thread_id,
            guild_id=int(guild_id),
        )

        embed = ModerationEmbedBuilder.build_admin_review_embed(embed_qo, self.bot.user)
        view = ObjectionManageView(self.bot)

        # 创建审核帖子
        thread_name = f"异议审核 - {dto.proposal_title[:50]}"
        thread_with_message = await self.bot.api_scheduler.submit(
            channel.create_thread(name=thread_name, embed=embed, view=view), priority=3
        )
        thread = thread_with_message[0]

        # 更新数据库中的审核帖子ID
        async with UnitOfWork(self.bot.db_handler) as uow:
            await uow.objection.update_objection_review_thread_id(dto.objection_id, thread.id)
            await uow.commit()

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
            # 获取帖子的启动消息
            original_message = review_thread.starter_message
            if not original_message:
                try:
                    original_message = await review_thread.fetch_message(review_thread.id)
                except discord.NotFound:
                    logger.warning(f"无法通过 API 拉取到审核帖子 {review_thread.id} 的启动消息。")
                    original_message = None

            if not original_message:
                logger.warning(f"审核帖子 {dto.review_thread_id} 中没有启动消息，无法更新。")
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

        except Exception as e:
            logger.error(
                f"更新审核帖子 {dto.review_thread_id} 的 Embed 时出错: {e}", exc_info=True
            )

    @commands.Cog.listener()
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
                user_id=interaction.user.id,
                message_id=interaction.message.id,
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
        logger.debug(f"接收到确认完成事件，上下文: {session.context}，目标ID: {session.target_id}")

        try:
            proposal_dto: ProposalDto | None = None
            target_status: ProposalStatus | None = None

            match session.context:
                case "proposal_execution":
                    proposal_dto = await self.logic.handle_proposal_execution_confirmed(
                        session.target_id
                    )
                    target_status = ProposalStatus.EXECUTING
                case "proposal_completion":
                    proposal_dto = await self.logic.handle_proposal_completion_confirmed(
                        session.target_id
                    )
                    target_status = ProposalStatus.FINISHED
                case "proposal_abandonment":
                    proposal_dto = await self.logic.handle_proposal_abandonment_confirmed(
                        session.target_id
                    )
                    target_status = ProposalStatus.ABANDONED
                case _:
                    logger.warning(f"未知的确认上下文: {session.context}")
                    return

            if proposal_dto and target_status and proposal_dto.discussion_thread_id:
                await self._update_thread_status_after_confirmation(
                    proposal_dto.discussion_thread_id,
                    proposal_dto.title,
                    target_status,
                )
            else:
                logger.warning(
                    "从 logic 层返回的 proposal_dto 为空，无法更新帖子状态。"
                    f"Proposal ID: {session.target_id}"
                )

        except Exception as e:
            logger.error(f"处理确认完成事件时出错: {e}", exc_info=True)

    async def _update_thread_status_after_confirmation(
        self, thread_id: int, title: str, target_status: ProposalStatus
    ):
        """根据确认结果更新帖子状态"""
        try:
            thread = await DiscordUtils.fetch_thread(self.bot, thread_id)
            if not thread:
                logger.warning(f"无法找到ID为 {thread_id} 的帖子，无法更新状态。")
                return

            # 将枚举映射到状态关键字
            status_key_map = {
                ProposalStatus.EXECUTING: "executing",
                ProposalStatus.FINISHED: "finished",
                ProposalStatus.ABANDONED: "abandoned",
            }
            status_key = status_key_map.get(target_status)

            if status_key:
                await self.thread_manager.update_status(thread, status_key)
            else:
                logger.warning(f"未知的提案状态: {target_status}，无法更新帖子。")

        except Exception as e:
            logger.error(f"更新帖子 {thread_id} 状态时发生未知错误: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_vote_view_raise_objection_clicked(self, interaction: discord.Interaction):
        """处理来自帖子内投票视图"发起异议"按钮的点击"""
        try:
            # 既然是从帖子内点击，可以直接获取信息
            if not interaction.channel or not interaction.guild:
                await interaction.response.send_message("此交互似乎已失效。", ephemeral=True)
                return

            # 构建提案链接
            proposal_link = (
                f"https://discord.com/channels/{interaction.guild.id}/{interaction.channel.id}"
            )

            # 创建并预填异议模态框
            modal = ObjectionModal(self.bot, proposal_link=proposal_link)

            # 发送模态框给用户
            await interaction.response.send_modal(modal)

        except Exception as e:
            logger.error(f"处理帖子内发起异议点击时出错: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.response.send_message("处理请求时出错", ephemeral=True), 1
            )

    @commands.Cog.listener()
    async def on_voting_channel_raise_objection_clicked(self, interaction: discord.Interaction):
        """处理来自投票频道"发起异议"按钮的点击"""
        try:
            if not interaction.message or not interaction.guild:
                await interaction.response.send_message("此交互似乎已失效。", ephemeral=True)
                return

            async with UnitOfWork(self.bot.db_handler) as uow:
                session = await uow.vote_session.get_vote_session_by_voting_channel_message_id(
                    interaction.message.id
                )

                if not session or not session.context_thread_id:
                    await interaction.response.send_message(
                        "找不到关联的原始投票信息。", ephemeral=True
                    )
                    return

                # 在 with 块内部安全地访问 session 对象的属性，并存入局部变量
                context_thread_id = session.context_thread_id
                guild_id = interaction.guild.id

            # 构建提案链接
            proposal_link = f"https://discord.com/channels/{guild_id}/{context_thread_id}"

            # 创建异议模态框
            modal = ObjectionModal(self.bot, proposal_link=proposal_link)

            await interaction.response.send_modal(modal)

        except Exception as e:
            logger.error(f"处理投票频道发起异议点击时出错: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.response.send_message("处理请求时出错", ephemeral=True), 1
            )
