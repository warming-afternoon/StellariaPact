import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from StellariaPact.cogs.Moderation.dto.ObjectionInitiationDto import \
    ObjectionInitiationDto
from StellariaPact.cogs.Moderation.logic.ModerationLogic import ModerationLogic
from StellariaPact.cogs.Moderation.qo.BuildConfirmationEmbedQo import \
    BuildConfirmationEmbedQo
from StellariaPact.cogs.Moderation.views.AbandonReasonModal import \
    AbandonReasonModal
from StellariaPact.cogs.Moderation.views.ConfirmationView import \
    ConfirmationView
from StellariaPact.cogs.Moderation.views.ModerationEmbedBuilder import \
    ModerationEmbedBuilder
from StellariaPact.cogs.Moderation.views.ObjectionAdminReviewView import \
    ObjectionAdminReviewView
from StellariaPact.cogs.Moderation.views.ObjectionCreationVoteView import \
    ObjectionCreationVoteView
from StellariaPact.cogs.Moderation.views.ObjectionModal import ObjectionModal
from StellariaPact.cogs.Moderation.views.ReasonModal import ReasonModal
from StellariaPact.cogs.Voting.dto.VoteSessionDto import VoteSessionDto
from StellariaPact.cogs.Voting.dto.VoteStatusDto import VoteStatusDto
from StellariaPact.models.Objection import Objection
from StellariaPact.models.Proposal import Proposal
from StellariaPact.share.auth.RoleGuard import RoleGuard
from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.StringUtils import StringUtils
from StellariaPact.share.UnitOfWork import UnitOfWork

logger = logging.getLogger("stellaria_pact.moderation")


class Moderation(commands.Cog):
    """
    处理所有与议事管理相关的命令和交互。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.logic = ModerationLogic(bot)
        self.kick_proposal_context_menu = app_commands.ContextMenu(
            name="踢出提案", callback=self.kick_proposal, type=discord.AppCommandType.message
        )
        self.bot.tree.add_command(self.kick_proposal_context_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(
            self.kick_proposal_context_menu.name, type=self.kick_proposal_context_menu.type
        )

    @RoleGuard.requireRoles(
        "councilModerator",
    )
    async def kick_proposal(self, interaction: discord.Interaction, message: discord.Message):
        """
        消息右键菜单命令，用于将消息作者踢出提案。
        """
        # 确保在可以发送消息的帖子中使用
        if not isinstance(interaction.channel, discord.Thread):
            await self.bot.api_scheduler.submit(
                coro=interaction.response.send_message("此命令只能在帖子内使用。", ephemeral=True),
                priority=1,
            )
            return

        # 类型守卫，确保 interaction.user 是 Member 类型
        if not isinstance(interaction.user, discord.Member):
            await self.bot.api_scheduler.submit(
                coro=interaction.response.send_message(
                    "无法验证您的身份，操作失败。", ephemeral=True
                ),
                priority=1,
            )
            return

        # 逻辑检查：禁止对机器人消息使用
        if message.author.bot:
            await self.bot.api_scheduler.submit(
                coro=interaction.response.send_message("不能对机器人执行此操作。", ephemeral=True),
                priority=1,
            )
            return

        # 逻辑检查：禁止对执行者本人使用
        if interaction.user.id == message.author.id:
            await self.bot.api_scheduler.submit(
                coro=interaction.response.send_message("不能对自己执行此操作。", ephemeral=True),
                priority=1,
            )
            return

        # 创建一个 ReasonModal 实例，并将所有需要的上下文传递给它。
        modal = ReasonModal(bot=self.bot, original_interaction=interaction, target_message=message)
        await self.bot.api_scheduler.submit(
            coro=interaction.response.send_modal(modal), priority=1
        )

    @commands.Cog.listener()
    async def on_proposal_thread_created(self, thread_id: int, proposer_id: int, title: str):
        """
        监听由 Voting cog 分派的提案帖子创建事件。
        """
        logger.info(
            f"接收到提案创建事件，帖子ID: {thread_id}, 发起人ID: {proposer_id}, 标题: {title}"
        )
        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                await uow.moderation.create_proposal(
                    thread_id=thread_id, proposer_id=proposer_id, title=title
                )
                await uow.commit()
        except Exception as e:
            logger.error(f"处理提案创建事件时发生错误 (帖子ID: {thread_id}): {e}", exc_info=True)

    @app_commands.command(name="进入执行", description="将提案状态变更为执行中")
    @RoleGuard.requireRoles("councilModerator", "executionAuditor")
    async def execute_proposal(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not isinstance(interaction.channel, discord.Thread) or not interaction.guild:
            return await interaction.followup.send("此命令只能在服务器的帖子内使用。", ephemeral=True)
        
        if not isinstance(interaction.user, discord.Member):
            return await interaction.followup.send("无法获取您的成员信息。", ephemeral=True)

        try:
            result_dto = await self.logic.handle_execute_proposal(
                channel_id=interaction.channel.id,
                guild_id=interaction.guild.id,
                user_id=interaction.user.id,
                user_role_ids={role.id for role in interaction.user.roles},
            )

            if not result_dto:
                return await interaction.followup.send("执行失败，无法获取处理结果。", ephemeral=True)

            # --- 构建 UI & 发送消息 ---
            role_display_names = {}
            for role_key, role_id_str in result_dto.role_display_names.items():
                role = interaction.guild.get_role(int(role_id_str))
                role_display_names[role_key] = role.name if role else role_key

            qo = BuildConfirmationEmbedQo(
                status=result_dto.session_dto.status,
                canceler_id=result_dto.session_dto.canceler_id,
                confirmed_parties=result_dto.session_dto.confirmed_parties,
                required_roles=result_dto.session_dto.required_roles,
                role_display_names=role_display_names,
            )
            
            if not self.bot.user:
                return await interaction.followup.send("机器人尚未准备好，无法发送消息。", ephemeral=True)

            embed = ModerationEmbedBuilder.build_confirmation_embed(qo, self.bot.user)
            view = ConfirmationView(self.bot)
            
            message = await interaction.channel.send(embed=embed, view=view)

            # --- 更新消息ID (通过Logic层) ---
            await self.logic.update_session_message_id(
                session_id=result_dto.session_dto.id, message_id=message.id
            )
            
            await interaction.followup.send("确认流程已成功发起。", ephemeral=True)

        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
        except Exception as e:
            logger.error(f"处理 'execute_proposal' 命令时发生意外错误: {e}", exc_info=True)
            await interaction.followup.send("发生未知错误，请联系技术员。", ephemeral=True)

    @app_commands.command(name="废弃", description="将执行中的提案废弃")
    @RoleGuard.requireRoles("executionAuditor")
    async def abandon_proposal(self, interaction: discord.Interaction):
        """
        通过弹出一个模态框来废弃一个提案。
        """
        modal = AbandonReasonModal(self.bot)
        await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), 1)

    @app_commands.command(name="发起异议", description="对一个提案发起异议")
    @RoleGuard.requireRoles("stewards")
    async def raise_objection(self, interaction: discord.Interaction):
        """
        处理 /发起异议 命令。
        """
        modal = ObjectionModal(self.bot)

        async def on_submit(interaction: discord.Interaction):
            await self.bot.api_scheduler.submit(safeDefer(interaction, ephemeral=True), 1)

            proposal_link = modal.proposal_link.value
            reason = modal.reason.value

            try:
                # 1. 确定目标帖子ID
                target_thread_id = None
                if proposal_link:
                    thread_id = StringUtils.extract_thread_id_from_url(proposal_link)
                    if not thread_id:
                        raise ValueError("提供的链接格式不正确，无法识别帖子ID。")
                    target_thread_id = thread_id
                elif isinstance(interaction.channel, discord.Thread):
                    target_thread_id = interaction.channel.id
                else:
                    raise ValueError("此命令必须在提案帖子内使用，或通过“提案链接”参数指定目标帖子。")

                # 2. 核心逻辑
                result_dto = await self.logic.handle_raise_objection(
                    user_id=interaction.user.id,
                    target_thread_id=target_thread_id,
                    reason=reason,
                )
                
                if not result_dto:
                    raise ValueError("执行失败，无法获取处理结果。")

                await self.bot.api_scheduler.submit(
                    interaction.followup.send(result_dto.message, ephemeral=True), 1
                )

            except ValueError as e:
                await self.bot.api_scheduler.submit(
                    interaction.followup.send(str(e), ephemeral=True), 1
                )
            except Exception as e:
                logger.error(f"处理 'raise_objection' 命令时发生意外错误: {e}", exc_info=True)
                await self.bot.api_scheduler.submit(
                    interaction.followup.send("发生未知错误，请联系技术员。", ephemeral=True), 1
                )

        modal.on_submit = on_submit
        await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), 1)

    @commands.Cog.listener()
    async def on_objection_creation_vote_initiation(self, event_dto: ObjectionInitiationDto):
        """
        监听“异议产生票”发起事件，在公示频道创建投票。
        """
        logger.info(f"****** 监听到 on_objection_creation_vote_initiation 事件，异议ID: {event_dto.objection_id} ******")
        try:
            channel_id = self.bot.config.get("channels", {}).get("objection_publicity")
            if not channel_id:
                logger.error("未在 config.json 中配置 'objection_publicity' 频道ID。")
                return

            channel = self.bot.get_channel(int(channel_id))
            if not isinstance(channel, discord.TextChannel):
                logger.error(f"无法找到ID为 {channel_id} 的文本频道，或类型不正确。")
                return

            # 定义一个发送消息的协程，它将被传递到 Logic 层
            async def message_sender(embed: discord.Embed) -> Optional[int]:
                view = ObjectionCreationVoteView(self.bot, event_dto.objection_id)
                message = await self.bot.api_scheduler.submit(
                    channel.send(embed=embed, view=view), priority=5
                )
                return message.id if message else None

            # 调用 Logic 层处理整个流程
            await self.logic.handle_objection_creation_vote_initiation(event_dto, message_sender)

        except Exception as e:
            logger.error(
                f"处理 on_objection_creation_vote_initiation (异议ID: {event_dto.objection_id}) 时发生错误: {e}",
                exc_info=True,
            )

    @commands.Cog.listener()
    async def on_objection_admin_review_initiation(self, event_dto: ObjectionInitiationDto):
        """
        监听非首次异议的管理员审核发起事件。
        """
        logger.info(f"接收到异议审核发起事件，异议ID: {event_dto.objection_id}，开始处理UI。")
        try:
            # 1. 从 Logic 层获取构建 Embed 所需的数据
            embed_qo = await self.logic.handle_objection_admin_review_initiation(event_dto)

            # 2. 获取频道和机器人用户
            channel_id = self.bot.config.get("channels", {}).get("review_channel")
            if not channel_id:
                logger.error("未在 config.json 中配置 'review_channel' 频道ID。")
                return

            channel = self.bot.get_channel(int(channel_id))
            if not isinstance(channel, discord.TextChannel):
                logger.error(f"无法找到ID为 {channel_id} 的审核频道，或类型不正确。")
                return

            if not self.bot.user:
                logger.error("机器人尚未登录，无法创建审核帖子。")
                return

            # 3. 构建 Embed 和 View
            embed = ModerationEmbedBuilder.build_admin_review_embed(embed_qo, self.bot.user)
            view = ObjectionAdminReviewView(self.bot, event_dto.objection_id)

            # 4. 发送消息并创建帖子
            thread_name = f"异议审核 - {event_dto.proposal_title[:50]}"
            message = await self.bot.api_scheduler.submit(
                channel.send(embed=embed, view=view), priority=3
            )
            thread = await self.bot.api_scheduler.submit(
                message.create_thread(name=thread_name), priority=3
            )
            logger.info(
                f"已为异议 {event_dto.objection_id} 在频道 {channel.id} 中创建了审核帖子 {thread.id}。"
            )

            # 5. 在数据库中关联审核帖子ID和异议
            async with UnitOfWork(self.bot.db_handler) as uow:
                await uow.moderation.update_objection_review_thread_id(
                    event_dto.objection_id, thread.id
                )
                await uow.commit()

        except Exception as e:
            logger.error(
                f"处理 on_objection_admin_review_initiation (异议ID: {event_dto.objection_id}) 时发生错误: {e}",
                exc_info=True,
            )

    @commands.Cog.listener()
    async def on_objection_formal_vote_initiation(
        self, objection: Objection, proposal: Proposal
    ):
        """
        监听正式异议投票发起事件，在公示频道创建投票。
        """
        logger.info(f"接收到正式异议投票发起事件，异议ID: {objection.id}，分派到 logic 层处理。")
        await self.logic.handle_objection_formal_vote_initiation(objection, proposal)

    @commands.Cog.listener()
    async def on_objection_vote_finished(
        self, session_dto: VoteSessionDto, result_dto: VoteStatusDto
    ):
        """
        监听由 VoteCloser 分派的异议投票结束事件。
        """
        logger.info(f"接收到异议投票结束事件，异议ID: {session_dto.objectionId}，分派到 logic 层处理。")
        try:
            result = await self.logic.handle_objection_vote_finished(session_dto, result_dto)

            if not result:
                logger.warning(f"处理异议投票结束事件 (异议ID: {session_dto.objectionId}) 未返回有效结果。")
                return

            if not self.bot.user:
                logger.error("机器人尚未登录，无法发送结果通知。")
                return

            channel = self.bot.get_channel(result.channel_id) if result.channel_id else None
            if not isinstance(channel, discord.TextChannel):
                logger.error(f"无法找到ID为 {result.channel_id} 的文本频道，或类型不正确。")
                return

            embed = ModerationEmbedBuilder.build_vote_result_embed(result.embed_qo, self.bot.user)

            # 尝试编辑原消息
            if result.message_id:
                try:
                    original_message = await channel.fetch_message(result.message_id)
                    await self.bot.api_scheduler.submit(
                        original_message.edit(embed=embed, view=None), priority=5
                    )
                    return # 成功编辑后即可返回
                except discord.NotFound:
                    logger.warning(f"无法找到原始投票消息 {result.message_id}，将发送新消息。")
                except Exception as e:
                    logger.error(f"更新原始投票消息 {result.message_id} 时出错: {e}", exc_info=True)
            
            # 如果编辑失败或没有 message_id，则发送新消息
            await self.bot.api_scheduler.submit(channel.send(embed=embed), priority=5)

        except Exception as e:
            logger.error(f"在 on_objection_vote_finished 中发生意外错误: {e}", exc_info=True)

    @commands.Cog.listener("on_announcement_finished")
    async def on_announcement_finished(self, announcement):
        """
        监听由 Notification cog 分派的公示结束事件。
        """
        logger.info(f"接收到公示结束事件，帖子ID: {announcement.discussionThreadId}，分派到 logic 层处理。")
        await self.logic.handle_announcement_finished(announcement)
