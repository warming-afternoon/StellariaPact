import logging
from typing import Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands

from StellariaPact.cogs.Moderation.dto.ExecuteProposalResultDto import ExecuteProposalResultDto
from StellariaPact.cogs.Moderation.dto.ObjectionVotePanelDto import ObjectionVotePanelDto
from StellariaPact.cogs.Moderation.dto.SubsequentObjectionDto import SubsequentObjectionDto
from StellariaPact.cogs.Moderation.ModerationLogic import ModerationLogic
from StellariaPact.cogs.Moderation.qo.BuildAdminReviewEmbedQo import BuildAdminReviewEmbedQo
from StellariaPact.cogs.Moderation.qo.BuildConfirmationEmbedQo import BuildConfirmationEmbedQo
from StellariaPact.cogs.Moderation.thread_manager import ProposalThreadManager
from StellariaPact.cogs.Moderation.views.AbandonReasonModal import AbandonReasonModal
from StellariaPact.cogs.Moderation.views.ConfirmationView import ConfirmationView
from StellariaPact.cogs.Moderation.views.ModerationEmbedBuilder import ModerationEmbedBuilder
from StellariaPact.cogs.Moderation.views.ObjectionManageView import ObjectionManageView
from StellariaPact.cogs.Moderation.views.ObjectionModal import ObjectionModal
from StellariaPact.cogs.Moderation.views.KickProposalModal import KickProposalModal
from StellariaPact.share.auth.PermissionGuard import PermissionGuard
from StellariaPact.share.auth.RoleGuard import RoleGuard
from StellariaPact.share.DiscordUtils import DiscordUtils
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
        self.kick_proposal_context_menu = app_commands.ContextMenu(
            name="踢出提案", callback=self.kick_proposal, type=discord.AppCommandType.message
        )

    def cog_load(self) -> None:
        """在 Cog 被添加到 Bot 后，进行依赖注入和初始化"""
        self.logic: ModerationLogic = ModerationLogic(self.bot)
        self.thread_manager = ProposalThreadManager(self.bot.config)
        self.bot.tree.add_command(self.kick_proposal_context_menu)

    async def cog_unload(self):
        self.bot.tree.remove_command(
            self.kick_proposal_context_menu.name, type=self.kick_proposal_context_menu.type
        )

    @RoleGuard.requireRoles(
        "councilModerator",
    )
    async def kick_proposal(self, interaction: discord.Interaction, message: discord.Message):
        """[议事督导] 消息右键菜单命令，用于将消息作者踢出提案。

        Args:
            interaction (discord.Interaction): 交互对象。
            message (discord.Message): 目标消息。
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

        # 创建 KickProposalModal 实例
        modal = KickProposalModal(bot=self.bot, original_interaction=interaction, target_message=message)
        await self.bot.api_scheduler.submit(
            coro=interaction.response.send_modal(modal), priority=1
        )

    @app_commands.command(
        name="进入执行", description="[议事督导+执行监理] 将讨论中的提案变更为执行中"
    )
    @RoleGuard.requireRoles("councilModerator", "executionAuditor")
    @app_commands.rename(notify_roles="通知相关方")
    @app_commands.describe(notify_roles="是否在发起确认时通知督导和监理组 (默认为是)")
    async def execute_proposal(self, interaction: discord.Interaction, notify_roles: bool = True):
        """将讨论中的提案变更为执行中。

        Args:
            interaction (discord.Interaction): 命令交互对象。
            notify_roles (bool): 是否通知相关方，默认为是。
        """
        await self._handle_confirmation_command(
            interaction, self.logic.handle_execute_proposal, notify_roles
        )

    @app_commands.command(
        name="提案完成", description="[议事督导+执行监理] 将执行中的提案变更为已结束"
    )
    @RoleGuard.requireRoles("councilModerator", "executionAuditor")
    @app_commands.rename(notify_roles="通知相关方")
    @app_commands.describe(notify_roles="是否在发起确认时通知督导和监理组 (默认为是)")
    async def complete_proposal(self, interaction: discord.Interaction, notify_roles: bool = True):
        """将执行中的提案变更为已结束。

        Args:
            interaction (discord.Interaction): 命令交互对象。
            notify_roles (bool): 是否通知相关方，默认为是。
        """
        await self._handle_confirmation_command(
            interaction, self.logic.handle_complete_proposal, notify_roles
        )

    @app_commands.command(name="废弃", description="[执行监理] 将执行中的提案废弃")
    @RoleGuard.requireRoles("executionAuditor")
    async def abandon_proposal(self, interaction: discord.Interaction):
        """通过弹出一个模态框来废弃一个提案。

        Args:
            interaction (discord.Interaction): 命令交互对象。
        """
        modal = AbandonReasonModal(self.bot, self.thread_manager)
        await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), 1)

    @app_commands.command(name="发起异议", description="对一个提案发起异议")
    async def raise_objection(self, interaction: discord.Interaction):
        """处理 /发起异议 命令，通过模态框收集信息。
        实际处理逻辑由 on_objection_modal_submitted 监听器完成。

        Args:
            interaction (discord.Interaction): 命令交互对象。
        """
        modal = ObjectionModal(self.bot)
        await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), 1)


    @app_commands.command(
        name="创建提案投票",
        description="[提案人/议事督导/执行监理] 为当前帖子手动创建一个提案投票",
    )
    @app_commands.describe(
        duration_hours="投票持续时间（小时），默认为 48 小时。",
        anonymous="是否匿名投票，默认为 是。",
        realtime="是否实时显示票数，默认为 是。",
        notify="投票结束时是否通知提案委员，默认为 是。",
        create_in_voting_channel="是否在投票频道创建镜像投票，默认为 是。",
    )
    async def create_proposal_vote(
        self,
        interaction: discord.Interaction,
        duration_hours: app_commands.Range[int, 1, 720] = 48,
        anonymous: bool = True,
        realtime: bool = True,
        notify: bool = True,
        create_in_voting_channel: bool = True,
    ):
        """为当前帖子手动创建一个提案投票。

        Args:
            interaction (discord.Interaction): 命令交互对象。
            duration_hours (app_commands.Range[int, 1, 720], optional): 投票持续时间（小时）。默认为 48。
            anonymous (bool, optional): 是否匿名投票。默认为 True。
            realtime (bool, optional): 是否实时显示票数。默认为 True。
            create_in_voting_channel (bool, optional): 是否在投票频道创建镜像投票。默认为 True。
        """
        await safeDefer(interaction, ephemeral=True)

        if not isinstance(interaction.channel, discord.Thread):
            await interaction.followup.send("此命令只能在提案帖子内使用。", ephemeral=True)
            return

        # 权限检查
        can_create = await PermissionGuard.can_manage_vote(interaction)
        if not can_create:
            await interaction.followup.send("您没有权限在此帖子中创建投票。", ephemeral=True)
            return

        thread = interaction.channel

        try:
            # 1. 获取发起人信息
            starter_message = thread.starter_message
            if not starter_message:
                starter_message = await thread.fetch_message(thread.id)

            if not starter_message:
                await interaction.followup.send(
                    "无法获取帖子的启动消息，操作失败。", ephemeral=True
                )
                return

            proposer_id = StringUtils.extract_proposer_id_from_content(starter_message.content)

            # 如果正则没有匹配到，则回退到使用消息作者ID作为备用方案
            if not proposer_id:
                proposer_id = starter_message.author.id

            clean_title = StringUtils.clean_title(thread.name)
            content = starter_message.content

            async with UnitOfWork(self.bot.db_handler) as uow:
                # 2. 尝试创建提案
                proposal_dto = await uow.moderation.create_proposal(
                    thread.id, proposer_id, clean_title, content
                )
                # 如果提案已存在，则获取它
                if not proposal_dto:
                    proposal_dto = await uow.moderation.get_proposal_by_thread_id(thread.id)

                await uow.commit()

            # 3. 派发事件以创建投票
            if proposal_dto:
                self.bot.dispatch(
                    "proposal_created",
                    proposal_dto,
                    duration_hours,
                    anonymous,
                    realtime,
                    notify,
                    create_in_voting_channel,
                )
                await interaction.followup.send("✅ 成功为本帖创建了新的投票！", ephemeral=True)
            else:
                await interaction.followup.send("处理提案信息失败，无法创建投票。", ephemeral=True)
        except Exception as e:
            logger.error(f"手动创建提案投票时出错: {e}", exc_info=True)
            await interaction.followup.send(f"发生错误: {e}", ephemeral=True)

    # --- 私有方法 ---

    async def _handle_confirmation_command(
        self,
        interaction: discord.Interaction,
        logic_handler: Callable[..., Awaitable[ExecuteProposalResultDto | None]],
        notify_roles: bool,
    ):
        """处理需要双重确认的命令（如 /进入执行, /完成提案）的通用逻辑。

        Args:
            interaction (discord.Interaction): 命令的交互对象。
            logic_handler (Callable[..., Awaitable[ExecuteProposalResultDto | None]]): 要调用的具体逻辑处理函数。
            notify_roles (bool): 是否在发起确认时通知相关方。
        """
        await self.bot.api_scheduler.submit(
            interaction.response.defer(ephemeral=True, thinking=True), 1
        )

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
