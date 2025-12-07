import logging
from typing import Awaitable, Callable

import discord
from discord import app_commands
from discord.ext import commands

from StellariaPact.cogs.Moderation.dto.ExecuteProposalResultDto import ExecuteProposalResultDto
from StellariaPact.cogs.Moderation.ModerationLogic import ModerationLogic
from StellariaPact.cogs.Moderation.qo.BuildConfirmationEmbedQo import BuildConfirmationEmbedQo
from StellariaPact.cogs.Moderation.thread_manager import ProposalThreadManager
from StellariaPact.cogs.Moderation.views.AbandonReasonModal import AbandonReasonModal
from StellariaPact.cogs.Moderation.views.ConfirmationView import ConfirmationView
from StellariaPact.cogs.Moderation.views.KickProposalModal import KickProposalModal
from StellariaPact.cogs.Moderation.views.ModerationEmbedBuilder import ModerationEmbedBuilder
from StellariaPact.cogs.Moderation.views.ObjectionModal import ObjectionModal
from StellariaPact.cogs.Moderation.views.VoteOptionsModal import VoteOptionsModal
from StellariaPact.dto.ProposalDto import ProposalDto
from StellariaPact.share.auth.PermissionGuard import PermissionGuard
from StellariaPact.share.auth.RoleGuard import RoleGuard
from StellariaPact.share.enums.VoteDuration import VoteDuration
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.StringUtils import StringUtils
from StellariaPact.share.UnitOfWork import UnitOfWork

logger = logging.getLogger(__name__)


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
        """
        [议事督导] 消息右键菜单命令，用于将消息作者踢出提案。

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
        modal = KickProposalModal(
            bot=self.bot, original_interaction=interaction, target_message=message
        )
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
        """
        将讨论中的提案变更为执行中。

        Args:
            interaction (discord.Interaction): 命令交互对象。
            notify_roles (bool): 是否通知相关方，默认为是。
        """
        await self._handle_confirmation_command(
            interaction, self.logic.handle_execute_proposal, notify_roles
        )

    @app_commands.command(
        name="提案完成", description="[议事督导+执行监理] 将讨论中或执行中的提案变更为已结束"
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

    @app_commands.command(
        name="废弃", description="[议事督导+执行监理] 将讨论中、冻结中或执行中的提案废弃"
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

    @app_commands.command(name="发起异议", description="对一个提案发起异议")
    async def raise_objection(self, interaction: discord.Interaction):
        """
        处理 /发起异议 命令，通过模态框收集信息。
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
    @app_commands.rename(
        duration_hours="投票持续时间",
        anonymous="是否匿名",
        realtime="实时票数",
        notify="结束时通知提案委员",
        create_in_voting_channel="创建镜像投票",
        notify_creation_role="通知投票创建身份组",
    )
    @app_commands.describe(
        duration_hours="投票持续时间（小时），默认为 72 小时",
        anonymous="是否匿名投票，默认为 是",
        realtime="是否实时显示票数，默认为 是",
        notify="投票结束时是否通知提案委员，默认为 是",
        create_in_voting_channel="是否在投票频道创建镜像投票，默认为 是",
        notify_creation_role="是否通知“投票创建”身份组,默认否",
    )
    async def create_proposal_vote(
        self,
        interaction: discord.Interaction,
        duration_hours: app_commands.Range[int, 1, 720] = VoteDuration.PROPOSAL_DEFAULT,
        anonymous: bool = True,
        realtime: bool = True,
        notify: bool = True,
        create_in_voting_channel: bool = True,
        notify_creation_role: bool = False,
    ):
        """为当前帖子手动创建一个提案投票。

        Args:
            interaction (discord.Interaction): 命令交互对象。
            duration_hours (app_commands.Range[int, 1, 720], optional): 投票持续时间（小时）。
                默认为 72。
            anonymous (bool, optional): 是否匿名投票。默认为 True
            realtime (bool, optional): 是否实时显示票数。默认为 True
            notify (bool, optional): 投票结束时是否通知提案委员。默认为 True
            create_in_voting_channel (bool, optional): 是否在投票频道创建镜像投票。默认为 True
            notify_creation_role (bool, optional): 是否通知创建身份组。默认为 False
        """

        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("此命令只能在提案帖子内使用。", ephemeral=True)
            return

        # 收集命令参数以便传递给 Modal
        command_args = {
            "duration_hours": duration_hours,
            "anonymous": anonymous,
            "realtime": realtime,
            "notify": notify,
            "create_in_voting_channel": create_in_voting_channel,
            "notify_creation_role": notify_creation_role,
        }

        # 弹出 Modal 以收集选项
        modal = VoteOptionsModal(
            bot=self.bot,
            moderation_cog=self,
            original_interaction=interaction,
            **command_args,
        )
        await interaction.response.send_modal(modal)

    async def process_proposal_and_vote_creation(
        self,
        interaction: discord.Interaction,
        options: list[str],
        duration_hours: int,
        anonymous: bool,
        realtime: bool,
        notify: bool,
        create_in_voting_channel: bool,
        notify_creation_role: bool,
    ):
        """由 VoteOptionsModal 提交后调用的核心逻辑"""
        if not isinstance(interaction.channel, discord.Thread):
            return

        # 权限检查
        can_create = await PermissionGuard.can_manage_vote(interaction)
        if not can_create:
            await interaction.edit_original_response(content="您没有权限在此帖子中创建投票。")
            return

        thread = interaction.channel

        try:
            raw_content = await StringUtils.extract_starter_content(thread)
            if not raw_content:
                await interaction.edit_original_response(
                    content="无法获取帖子的首楼内容，操作失败。"
                )
                return

            proposer_id = (
                StringUtils.extract_proposer_id_from_content(raw_content) or thread.owner_id
            )

            clean_content = StringUtils.clean_proposal_content(raw_content)
            clean_title = StringUtils.clean_title(thread.name)

            async with UnitOfWork(self.bot.db_handler) as uow:
                # 尝试创建提案
                proposal = await uow.proposal.create_proposal(
                    thread.id, proposer_id, clean_title, clean_content
                )
                # 如果提案已存在，则获取它
                if not proposal:
                    proposal = await uow.proposal.get_proposal_by_thread_id(thread.id)
                # 转换为 DTO 以供事件使用
                proposal_dto = ProposalDto.model_validate(proposal) if proposal else None
                await uow.commit()

            # 派发事件以创建投票
            if proposal_dto:
                self.bot.dispatch(
                    "proposal_created",
                    proposal_dto,
                    options,
                    duration_hours,
                    anonymous,
                    realtime,
                    notify,
                    create_in_voting_channel,
                    notify_creation_role,
                )
            else:
                await interaction.followup.send(content="处理提案信息失败，无法创建投票。")
        except Exception as e:
            logger.error(f"手动创建提案投票时出错: {e}", exc_info=True)
            await interaction.followup.send(content=f"发生错误: {e}")

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
            logic_handler (
                Callable[..., Awaitable[ExecuteProposalResultDto | None]]
            ): 要调用的具体逻辑处理函数。
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
