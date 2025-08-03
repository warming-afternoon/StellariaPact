import logging

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy.exc import IntegrityError

from StellariaPact.cogs.Moderation.dto.ConfirmationSessionDto import ConfirmationSessionDto
from StellariaPact.cogs.Moderation.qo.BuildConfirmationEmbedQo import BuildConfirmationEmbedQo
from StellariaPact.cogs.Moderation.qo.CreateConfirmationSessionQo import (
    CreateConfirmationSessionQo,
)
from StellariaPact.cogs.Moderation.views.AbandonReasonModal import AbandonReasonModal
from StellariaPact.cogs.Moderation.views.ConfirmationView import ConfirmationView
from StellariaPact.cogs.Moderation.views.ModerationEmbedBuilder import ModerationEmbedBuilder
from StellariaPact.cogs.Moderation.views.ReasonModal import ReasonModal
from StellariaPact.share.auth.RoleGuard import RoleGuard
from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.UnitOfWork import UnitOfWork

logger = logging.getLogger("stellaria_pact.moderation")


class Moderation(commands.Cog):
    """
    处理所有与议事管理相关的命令和交互。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
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
    async def on_proposal_thread_created(self, thread_id: int, proposer_id: int):
        """
        监听由 Voting cog 分派的提案帖子创建事件。
        """
        logger.info(f"接收到提案创建事件，帖子ID: {thread_id}, 发起人ID: {proposer_id}")
        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                await uow.moderation.create_proposal(thread_id=thread_id, proposer_id=proposer_id)
                await uow.commit()
        except Exception as e:
            logger.error(f"处理提案创建事件时发生错误 (帖子ID: {thread_id}): {e}", exc_info=True)

    @app_commands.command(name="进入执行", description="将提案状态变更为执行中")
    @RoleGuard.requireRoles("councilModerator", "executionAuditor")
    async def execute_proposal(self, interaction: discord.Interaction):
        await self.bot.api_scheduler.submit(safeDefer(interaction, ephemeral=True), 1)

        if not isinstance(interaction.channel, discord.Thread):
            return await self.bot.api_scheduler.submit(
                interaction.followup.send("此命令只能在帖子内使用。", ephemeral=True), 1
            )

        if not self.bot.user:
            return await self.bot.api_scheduler.submit(
                interaction.followup.send("机器人尚未完全准备好。", ephemeral=True), 1
            )

        if not isinstance(interaction.user, discord.Member):
            return await self.bot.api_scheduler.submit(
                interaction.followup.send("无法获取您的成员信息。", ephemeral=True), 1
            )

        # --- 事务一：读取提案信息 ---
        proposal_id: int | None = None
        async with UnitOfWork(self.bot.db_handler) as uow:
            proposal = await uow.moderation.get_proposal_by_thread_id(interaction.channel.id)
            if not proposal:
                return await self.bot.api_scheduler.submit(
                    interaction.followup.send("未找到关连的提案。", ephemeral=True), 1
                )
            if proposal.status != 0:  # 0: 讨论中
                return await self.bot.api_scheduler.submit(
                    interaction.followup.send(
                        "提案当前状态不是“讨论中”，无法执行此操作。", ephemeral=True
                    ),
                    1,
                )
            proposal_id = proposal.id

        # --- 事务二：创建会话（处理竞态条件） ---
        session_dto: ConfirmationSessionDto | None = None
        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                assert proposal_id is not None

                # 获取发起者拥有的角色键
                user_role_ids = {role.id for role in interaction.user.roles}
                config_roles = self.bot.config.get("roles", {})
                initiator_role_keys = [
                    key for key, val in config_roles.items() if int(val) in user_role_ids
                ]

                qo = CreateConfirmationSessionQo(
                    context="proposal_execution",
                    target_id=proposal_id,
                    required_roles=["councilModerator", "executionAuditor"],
                    initiator_id=interaction.user.id,
                    initiator_role_keys=initiator_role_keys,
                )
                session_dto = await uow.moderation.create_confirmation_session(qo)
                await uow.commit()
        except IntegrityError:
            logger.warning(
                f"创建确认会话时发生唯一性冲突 (proposal_id: {proposal_id})，可能由竞态条件引起。"
            )
            return await self.bot.api_scheduler.submit(
                interaction.followup.send(
                    "操作失败：此提案的确认流程刚刚已被另一位管理员发起。", ephemeral=True
                ),
                1,
            )

        if not session_dto:
            return await self.bot.api_scheduler.submit(
                interaction.followup.send("创建确认会话失败，请稍后再试。", ephemeral=True), 1
            )

        # --- 构建 UI & 发送消息 (事务外) ---
        role_display_names = {}
        if interaction.guild and hasattr(self.bot, "config"):
            roles_config = self.bot.config.get("roles", {})
            for role_key in session_dto.required_roles:
                role_id = roles_config.get(role_key)
                if role_id:
                    role = interaction.guild.get_role(int(role_id))
                    role_display_names[role_key] = role.name if role else role_key
                else:
                    role_display_names[role_key] = role_key

        qo = BuildConfirmationEmbedQo(
            status=session_dto.status,
            canceler_id=session_dto.canceler_id,
            confirmed_parties=session_dto.confirmed_parties,
            required_roles=session_dto.required_roles,
            role_display_names=role_display_names,
        )

        if not self.bot.user:
            # This should theoretically not be reached due to the check at the start
            return await self.bot.api_scheduler.submit(
                interaction.followup.send("机器人尚未准备好，无法构建消息。", ephemeral=True), 1
            )

        embed = ModerationEmbedBuilder.build_confirmation_embed(qo, self.bot.user)
        view = ConfirmationView(self.bot)

        message = await self.bot.api_scheduler.submit(
            interaction.channel.send(embed=embed, view=view), 1
        )

        # --- 事务三：更新消息ID ---
        async with UnitOfWork(self.bot.db_handler) as uow:
            await uow.moderation.update_confirmation_session_message_id(session_dto.id, message.id)
            await uow.commit()

        # --- 最终确认 ---
        await self.bot.api_scheduler.submit(
            interaction.followup.send("确认流程已成功发起。", ephemeral=True), 1
        )

    @app_commands.command(name="废弃", description="将执行中的提案废弃")
    @RoleGuard.requireRoles("executionAuditor")
    async def abandon_proposal(self, interaction: discord.Interaction):
        """
        通过弹出一个模态框来废弃一个提案。
        """
        modal = AbandonReasonModal(self.bot)
        await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), 1)

    @commands.Cog.listener("on_announcement_finished")
    async def on_announcement_finished(self, announcement):
        """
        监听由 Notification cog 分派的公示结束事件。
        """
        logger.debug(
            f"接收到公示结束事件，帖子ID: {announcement.discussionThreadId}, "
            f"公示标题: {announcement.title}"
        )
        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                await uow.moderation.update_proposal_status_by_thread_id(
                    thread_id=announcement.discussionThreadId,
                    status=1,  # 1: 执行中
                )
                await uow.commit()
        except Exception as e:
            logger.error(
                f"处理公示结束事件时发生错误 (帖子ID: {announcement.discussionThreadId}): {e}",
                exc_info=True,
            )
