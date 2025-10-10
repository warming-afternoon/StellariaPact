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

        Args:
            interaction (discord.Interaction): 命令交互对象。
        """
        modal = ObjectionModal(self.bot)

        async def on_submit(interaction: discord.Interaction):
            # 立即响应，防止超时
            await safeDefer(interaction, ephemeral=True)

            proposal_link = modal.proposal_link.value
            reason = modal.reason.value

            try:
                # --- 阶段一: 创建数据库记录 ---
                target_thread_id = self._determine_target_thread_id(interaction, proposal_link)

                # 调用 Logic 层，它现在根据情况返回不同类型的 DTO
                result_dto = await self.logic.handle_raise_objection(
                    user_id=interaction.user.id,
                    target_thread_id=target_thread_id,
                    reason=reason,
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
                logger.error(f"处理 'raise_objection' 命令时发生意外错误: {e}", exc_info=True)
                await self.bot.api_scheduler.submit(
                    interaction.followup.send("发生未知错误，请联系技术员。", ephemeral=True), 1
                )

        modal.on_submit = on_submit
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
    )
    async def create_proposal_vote(
        self,
        interaction: discord.Interaction,
        duration_hours: app_commands.Range[int, 1, 720] = 48,
        anonymous: bool = True,
        realtime: bool = True,
        notify: bool = True,
    ):
        """为当前帖子手动创建一个提案投票。

        Args:
            interaction (discord.Interaction): 命令交互对象。
            duration_hours (app_commands.Range[int, 1, 720], optional): 投票持续时间（小时）。默认为 48。
            anonymous (bool, optional): 是否匿名投票。默认为 True。
            realtime (bool, optional): 是否实时显示票数。默认为 True。
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

            async with UnitOfWork(self.bot.db_handler) as uow:
                # 2. 尝试创建提案
                proposal_dto = await uow.moderation.create_proposal(
                    thread.id, proposer_id, clean_title
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
                )
                await interaction.followup.send("✅ 成功为本帖创建了新的投票！", ephemeral=True)
            else:
                await interaction.followup.send("处理提案信息失败，无法创建投票。", ephemeral=True)
        except Exception as e:
            logger.error(f"手动创建提案投票时出错: {e}", exc_info=True)
            await interaction.followup.send(f"发生错误: {e}", ephemeral=True)

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
            await uow.moderation.update_objection_review_thread_id(dto.objection_id, thread.id)
            await uow.commit()

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
