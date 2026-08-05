import logging
from typing import Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands

from StellariaPact.cogs.Moderation.dto import ExecuteProposalResultDto
from StellariaPact.cogs.Moderation.ModerationLogic import ModerationLogic
from StellariaPact.cogs.Moderation.qo import BuildConfirmationEmbedQo
from StellariaPact.cogs.Moderation.thread_manager import ProposalThreadManager
from StellariaPact.cogs.Moderation.views.AbandonReasonModal import AbandonReasonModal
from StellariaPact.cogs.Moderation.views.ConfirmationView import ConfirmationView
from StellariaPact.cogs.Moderation.views.MaliciousObjectionHistoryModal import (
    MaliciousObjectionHistoryModal,
)
from StellariaPact.cogs.Moderation.views.ModerationEmbedBuilder import ModerationEmbedBuilder
from StellariaPact.cogs.Moderation.views.ObjectionRemovalModal import (
    ObjectionRemovalModal,
)
from StellariaPact.cogs.Moderation.views.SelfAbandonReasonModal import SelfAbandonReasonModal
from StellariaPact.dto import ProposalDto
from StellariaPact.share import StellariaPactBot, UnitOfWork, safeDefer
from StellariaPact.share.auth import RoleGuard
from StellariaPact.share.enums import ObjectionResolutionType, ProposalStatus

logger = logging.getLogger(__name__)


class Moderation(commands.Cog):
    """
    处理所有与议事管理相关的命令和交互。
    """

    proposal_group = app_commands.Group(
        name="提案",
        description="提案状态管理",
    )

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.remove_objection_ctx = app_commands.ContextMenu(
            name="提案组移除异议",
            callback=self.remove_objections_from_message,
            type=discord.AppCommandType.message,
        )
        self.view_malicious_objections_ctx = app_commands.ContextMenu(
            name="查看恶意违规异议",
            callback=self.view_malicious_objections_for_user,
            type=discord.AppCommandType.user,
        )

    def cog_load(self) -> None:
        """在 Cog 被添加到 Bot 后，进行依赖注入和初始化"""
        self.logic: ModerationLogic = ModerationLogic(self.bot)
        self.thread_manager = ProposalThreadManager(self.bot.config)
        self.bot.tree.add_command(self.remove_objection_ctx)
        self.bot.tree.add_command(self.view_malicious_objections_ctx)

    async def cog_unload(self):
        self.bot.tree.remove_command(
            self.remove_objection_ctx.name,
            type=self.remove_objection_ctx.type,
        )
        self.bot.tree.remove_command(
            self.view_malicious_objections_ctx.name,
            type=self.view_malicious_objections_ctx.type,
        )

    @RoleGuard.requireRoles("councilModerator", "executionAuditor")
    async def remove_objections_from_message(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
    ) -> None:
        """在提案帖内打开异议多选移除表单。"""
        if not isinstance(interaction.channel, discord.Thread) or not interaction.guild:
            await interaction.response.send_message(
                "此指令只能在提案帖子内使用。",
                ephemeral=True,
            )
            return

        try:
            options = await self.logic.get_latest_active_objections(
                interaction.channel.id
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        if not options:
            await interaction.response.send_message(
                "当前帖子没有进行中的异议。",
                ephemeral=True,
            )
            return

        modal = ObjectionRemovalModal(self, options)
        await self.bot.api_scheduler.submit(
            interaction.response.send_modal(modal),
            priority=1,
        )

    @RoleGuard.requireRoles("councilModerator", "executionAuditor")
    async def view_malicious_objections_for_user(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
    ) -> None:
        """查看当前服务器内用户最近的恶意违规异议。"""
        if not interaction.guild:
            await interaction.response.send_message(
                "此指令只能在服务器内使用。",
                ephemeral=True,
            )
            return

        async with UnitOfWork(self.bot.db_handler) as uow:
            total, records = await uow.vote_option.get_malicious_objection_summary(
                guild_id=interaction.guild.id,
                creator_id=member.id,
                limit=4,
            )
        modal = MaliciousObjectionHistoryModal(member, total, records)
        await self.bot.api_scheduler.submit(
            interaction.response.send_modal(modal),
            priority=1,
        )

    @proposal_group.command(
        name="进入执行", description="[议事督导+执行监理] 将讨论中的提案变更为执行中"
    )
    @RoleGuard.requireRoles("councilModerator", "executionAuditor")
    @app_commands.rename(notify_roles="通知相关方")
    @app_commands.describe(notify_roles="是否在发起确认时通知督导和监理组 (默认为是)")
    async def execute_proposal(self, interaction: discord.Interaction, notify_roles: bool = True):
        """
        将讨论中的提案变更为执行中。

        Args:
            interaction (discord.Interaction): 命令交互对象。
            notify_roles (bool): 是否通知相关方，默认为是。
        """
        await self._handle_confirmation_command(
            interaction, self.logic.handle_execute_proposal, notify_roles
        )

    @proposal_group.command(
        name="完成", description="[议事督导+执行监理] 将讨论中或执行中的提案变更为已结束"
    )
    @RoleGuard.requireRoles("councilModerator", "executionAuditor")
    @app_commands.rename(notify_roles="通知相关方")
    @app_commands.describe(notify_roles="是否在发起确认时通知督导和监理组 (默认为是)")
    async def complete_proposal(self, interaction: discord.Interaction, notify_roles: bool = True):
        """
        将讨论中或执行中的提案变更为已结束。

        Args:
            interaction (discord.Interaction): 命令交互对象。
            notify_roles (bool): 是否通知相关方，默认为是。
        """
        await self._handle_confirmation_command(
            interaction, self.logic.handle_complete_proposal, notify_roles
        )

    @proposal_group.command(
        name="废弃", description="[议事督导+执行监理] 将讨论中/执行中/异议中的提案废弃"
    )
    @RoleGuard.requireRoles("councilModerator", "executionAuditor")
    @app_commands.rename(notify_roles="通知相关方")
    @app_commands.describe(notify_roles="是否在发起确认时通知督导和监理组 (默认为是)")
    async def abandon_proposal(self, interaction: discord.Interaction, notify_roles: bool = True):
        """
        通过弹出一个模态框来废弃一个提案

        Args:
            interaction (discord.Interaction): 命令交互对象。
            notify_roles (bool): 是否通知相关方，默认为是。
        """
        modal = AbandonReasonModal(self.bot, self.thread_manager, self, notify_roles)
        await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), 1)

    @app_commands.command(
        name="自助废弃", description="[提案人] 提案发起人直接废弃自己的提案"
    )
    async def self_abandon_proposal(self, interaction: discord.Interaction):
        """
        通过弹出一个模态框来让提案发起人直接废弃自己的提案。
        此命令不检查管理权限，而是通过验证是否为提案所有人来放行。
        """
        if not isinstance(interaction.channel, discord.Thread):
            await self.bot.api_scheduler.submit(
                interaction.response.send_message(
                    "此命令只能在提案帖子内使用。", ephemeral=True
                ), 1
            )
            return

        # 获取提案数据并转换为DTO
        proposal_dto = None
        async with UnitOfWork(self.bot.db_handler) as uow:
            proposal = await uow.proposal.get_proposal_by_thread_id(interaction.channel.id)
            if proposal:
                proposal_dto = ProposalDto.model_validate(proposal)

        # 进行验证
        if not proposal_dto:
            await self.bot.api_scheduler.submit(
                interaction.response.send_message("未找到关连的提案。", ephemeral=True), 1
            )
            return

        if proposal_dto.proposer_id != interaction.user.id:
            await self.bot.api_scheduler.submit(
                interaction.response.send_message(
                    "只有提案发起人才能使用自助废弃功能", ephemeral=True
                ), 1
            )
            return

        valid_statuses = [
            ProposalStatus.DISCUSSION,
            ProposalStatus.FROZEN,
            ProposalStatus.EXECUTING,
            ProposalStatus.UNDER_OBJECTION
        ]
        if proposal_dto.status not in valid_statuses:
            await self.bot.api_scheduler.submit(
                interaction.response.send_message("提案当前状态不允许废弃。", ephemeral=True), 1
            )
            return

        # 弹出模态框收集原因
        modal = SelfAbandonReasonModal(self.bot, self.thread_manager, self)
        await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), 1)

    async def _handle_self_abandon(self, interaction: discord.Interaction, reason: str):
        """处理由自助废弃模态框提交过来的数据"""
        await safeDefer(interaction)

        if not isinstance(interaction.channel, discord.Thread):
            return

        try:
            # 发送状态变更 Embed
            embed = ModerationEmbedBuilder.build_status_change_embed(
                thread_name=interaction.channel.name,
                new_status="已废弃",
                moderator=interaction.user,
                reason=reason
            )
            await self.bot.api_scheduler.submit(
                interaction.followup.send(embed=embed, ephemeral=False), 2
            )

            # 调用 logic 层处理
            await self.logic.execute_self_abandon_proposal(
                channel_id=interaction.channel.id,
                user_id=interaction.user.id,
                reason=reason
            )

        except ValueError as e:
            # 对于预期的异常，仍作临时消息回应
            await self.bot.api_scheduler.submit(
                interaction.followup.send(str(e), ephemeral=True), 1
            )
        except Exception as e:
            logger.error(f"处理自助废弃时发生意外错误: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send("发生未知错误，请联系技术员。", ephemeral=True), 1
            )

    @proposal_group.command(
        name="重新讨论", description="[议事督导+执行监理] 将任何状态的提案恢复为讨论中"
    )
    @RoleGuard.requireRoles("councilModerator", "executionAuditor")
    @app_commands.rename(
        notify_roles="通知相关方",
        resolution_type="类型",
        description="描述",
    )
    @app_commands.describe(
        notify_roles="是否在发起确认时通知督导和监理组 (默认为是)",
        resolution_type="异议处理类型，默认正常流程",
        description="异议处理描述（可选，最多 500 字）",
    )
    @app_commands.choices(
        resolution_type=[
            app_commands.Choice(name="正常流程", value=1),
            app_commands.Choice(name="恶意违规", value=2),
        ]
    )
    async def rediscuss_proposal(
        self,
        interaction: discord.Interaction,
        notify_roles: bool = True,
        resolution_type: app_commands.Choice[int] | None = None,
        description: app_commands.Range[str, 1, 500] | None = None,
    ):
        """
        将提案变更为重新讨论中状态。

        Args:
            interaction (discord.Interaction): 命令交互对象。
            notify_roles (bool): 是否通知相关方，默认为是。
        """
        selected_type = (
            resolution_type.value
            if resolution_type is not None
            else int(ObjectionResolutionType.NORMAL)
        )

        async def rediscuss_handler(
            channel_id: int,
            guild_id: int,
            user_id: int,
            user_role_ids: set[int],
        ) -> ExecuteProposalResultDto | None:
            return await self.logic.handle_rediscuss_proposal(
                channel_id=channel_id,
                guild_id=guild_id,
                user_id=user_id,
                user_role_ids=user_role_ids,
                resolution_type=selected_type,
                description=description.strip() if description else None,
            )

        await self._handle_confirmation_command(
            interaction, rediscuss_handler, notify_roles
        )

    # -------------------------
    # 私有方法
    # -------------------------

    async def _handle_confirmation_command(
        self,
        interaction: discord.Interaction,
        logic_handler: Callable[..., Awaitable[ExecuteProposalResultDto | None]],
        notify_roles: bool,
    ):
        """处理需要双重确认的命令（如 /提案 进入执行、/提案 完成）的通用逻辑。

        Args:
            interaction (discord.Interaction): 命令的交互对象。
            logic_handler (
                Callable[..., Awaitable[ExecuteProposalResultDto | None]]
            ): 要调用的具体逻辑处理函数。
            notify_roles (bool): 是否在发起确认时通知相关方。
        """
        await safeDefer(interaction, ephemeral=True)

        if not isinstance(interaction.channel, discord.Thread) or not interaction.guild:
            return await self.bot.api_scheduler.submit(
                interaction.followup.send("此命令只能在服务器的帖子内使用。", ephemeral=True), 1
            )

        if not isinstance(interaction.user, discord.Member):
            return await self.bot.api_scheduler.submit(
                interaction.followup.send("无法获取您的成员信息。", ephemeral=True), 1
            )

        try:
            result_dto = await logic_handler(
                channel_id=interaction.channel.id,
                guild_id=interaction.guild.id,
                user_id=interaction.user.id,
                user_role_ids={role.id for role in interaction.user.roles},
            )

            if not result_dto:
                return await self.bot.api_scheduler.submit(
                    interaction.followup.send("执行失败，无法获取处理结果。", ephemeral=True),
                    1,
                )

            # --- 构建 UI & 发送消息 ---
            role_display_names = {}
            for role_key, role_id_str in result_dto.role_display_names.items():
                role = interaction.guild.get_role(int(role_id_str))
                role_display_names[role_key] = role.name if role else role_key

            qo = BuildConfirmationEmbedQo(
                context=result_dto.session_dto.context,
                status=result_dto.session_dto.status,
                canceler_id=result_dto.session_dto.canceler_id,
                confirmed_parties=result_dto.session_dto.confirmed_parties,
                required_roles=result_dto.session_dto.required_roles,
                role_display_names=role_display_names,
                reason=result_dto.session_dto.reason,
                payload=result_dto.session_dto.payload,
            )

            if not self.bot.user:
                return await self.bot.api_scheduler.submit(
                    interaction.followup.send("机器人尚未准备好，无法发送消息。", ephemeral=True),
                    1,
                )

            embed = ModerationEmbedBuilder.build_confirmation_embed(qo, self.bot.user)
            view = ConfirmationView(self.bot)

            content_to_send = None
            if notify_roles:
                roles_config = self.bot.config.get("roles", {})
                moderator_role_id = roles_config.get("councilModerator")
                auditor_role_id = roles_config.get("executionAuditor")

                pings = []
                if moderator_role_id:
                    pings.append(f"<@&{moderator_role_id}>")
                if auditor_role_id:
                    pings.append(f"<@&{auditor_role_id}>")

                if pings:
                    content_to_send = " ".join(pings)

            message = await self.bot.api_scheduler.submit(
                interaction.channel.send(content=content_to_send, embed=embed, view=view), 2
            )

            # --- 更新消息ID ---
            await self.logic.update_session_message_id(
                session_id=result_dto.session_dto.id, message_id=message.id
            )

            await self.bot.api_scheduler.submit(
                interaction.followup.send("确认流程已成功发起。", ephemeral=True), 1
            )

        except ValueError as e:
            await self.bot.api_scheduler.submit(
                interaction.followup.send(str(e), ephemeral=True), 1
            )
        except Exception as e:
            command_name = interaction.command.name if interaction.command else "unknown"
            logger.error(f"处理 '{command_name}' 命令时发生意外错误: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send("发生未知错误，请联系技术员。", ephemeral=True), 1
            )

    async def _initiate_abandon_confirmation(
        self, interaction: discord.Interaction, reason: str, notify_roles: bool
    ):
        """发起废弃提案的双重确认流程。

        Args:
            interaction (discord.Interaction): 交互对象。
            reason (str): 废弃原因。
            notify_roles (bool): 是否通知相关方。
        """

        async def abandon_handler(
            channel_id: int, guild_id: int, user_id: int, user_role_ids: set[int]
        ) -> ExecuteProposalResultDto | None:
            return await self.logic.handle_abandon_proposal(
                channel_id=channel_id,
                guild_id=guild_id,
                user_id=user_id,
                user_role_ids=user_role_ids,
                reason=reason,
            )

        await self._handle_confirmation_command(interaction, abandon_handler, notify_roles)

    async def _initiate_objection_removal_confirmation(
        self,
        *,
        interaction: discord.Interaction,
        option_ids: list[int],
        resolution_type: int,
        description: str | None,
    ) -> None:
        """为右键移除异议操作发起提案组双重确认。"""

        async def removal_handler(
            channel_id: int,
            guild_id: int,
            user_id: int,
            user_role_ids: set[int],
        ) -> ExecuteProposalResultDto | None:
            return await self.logic.handle_remove_objections(
                channel_id=channel_id,
                guild_id=guild_id,
                user_id=user_id,
                user_role_ids=user_role_ids,
                option_ids=option_ids,
                resolution_type=resolution_type,
                description=description,
            )

        await self._handle_confirmation_command(
            interaction,
            removal_handler,
            notify_roles=True,
        )
