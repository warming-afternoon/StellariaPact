import logging

import discord
from discord import app_commands
from discord.ext import commands

from StellariaPact.cogs.Moderation.dto.ObjectionVotePanelDto import \
    ObjectionVotePanelDto
from StellariaPact.cogs.Moderation.dto.SubsequentObjectionDto import \
    SubsequentObjectionDto
from StellariaPact.cogs.Moderation.ModerationLogic import ModerationLogic
from StellariaPact.cogs.Moderation.qo.BuildAdminReviewEmbedQo import \
    BuildAdminReviewEmbedQo
from StellariaPact.cogs.Moderation.qo.BuildConfirmationEmbedQo import \
    BuildConfirmationEmbedQo
from StellariaPact.cogs.Moderation.qo.BuildFirstObjectionEmbedQo import \
    BuildFirstObjectionEmbedQo
from StellariaPact.cogs.Moderation.views.AbandonReasonModal import \
    AbandonReasonModal
from StellariaPact.cogs.Moderation.views.ConfirmationView import \
    ConfirmationView
from StellariaPact.cogs.Moderation.views.ModerationEmbedBuilder import \
    ModerationEmbedBuilder
from StellariaPact.cogs.Moderation.views.ObjectionCreationVoteView import \
    ObjectionCreationVoteView
from StellariaPact.cogs.Moderation.views.ObjectionManageView import \
    ObjectionManageView
from StellariaPact.cogs.Moderation.views.ObjectionModal import ObjectionModal
from StellariaPact.cogs.Moderation.views.ReasonModal import ReasonModal
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

    @app_commands.command(name="进入执行", description="将提案状态变更为执行中")
    @RoleGuard.requireRoles("councilModerator", "executionAuditor")
    async def execute_proposal(self, interaction: discord.Interaction):
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
            result_dto = await self.logic.handle_execute_proposal(
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

            message = await self.bot.api_scheduler.submit(
                interaction.channel.send(embed=embed, view=view), 2
            )

            # --- 更新消息ID (通过Logic层) ---
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
            logger.error(f"处理 'execute_proposal' 命令时发生意外错误: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                interaction.followup.send("发生未知错误，请联系技术员。", ephemeral=True), 1
            )

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
            # 立即响应，防止超时
            await self.bot.api_scheduler.submit(safeDefer(interaction, ephemeral=True), 1)

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
                    # 如果返回 DTO，说明是首次异议，直接创建投票面板
                    assert isinstance(result_dto, ObjectionVotePanelDto)
                    await self._create_objection_collection_panel(result_dto, interaction)
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

    def _determine_target_thread_id(
        self, interaction: discord.Interaction, proposal_link: str
    ) -> int:
        """从交互上下文或链接中解析出目标帖子ID。"""
        if proposal_link:
            thread_id = StringUtils.extract_thread_id_from_url(proposal_link)
            if not thread_id:
                raise ValueError("提供的链接格式不正确，无法识别帖子ID。")
            return thread_id
        elif isinstance(interaction.channel, discord.Thread):
            return interaction.channel.id
        else:
            raise ValueError("此命令必须在提案帖子内使用，或通过“提案链接”参数指定目标帖子。")

    async def _create_objection_collection_panel(
        self, dto: ObjectionVotePanelDto, interaction: discord.Interaction | None = None
    ):
        """通用方法：根据 DTO 在公示频道创建异议收集面板"""
        # 获取频道
        channel_id_str = self.bot.config.get("channels", {}).get("objection_publicity")
        guild_id_str = self.bot.config.get("guild_id")
        guild = (
            interaction.guild
            if interaction
            else self.bot.get_guild(int(guild_id_str if guild_id_str else 0))
        )

        if not channel_id_str or not guild:
            raise RuntimeError("公示频道或服务器ID未配置，或无法获取服务器信息。")
        channel = await DiscordUtils.fetch_channel(self.bot, int(channel_id_str))

        # 类型守卫，确保公示频道是文本频道
        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError(f"异议公示频道 (ID: {channel_id_str}) 必须是一个文本频道。")

        # 构建 Embed 和 View
        objector = await self.bot.fetch_user(dto.objector_id)
        guild_id = guild.id

        proposal_url = f"https://discord.com/channels/{guild_id}/{dto.proposal_thread_id}"

        embed_qo = BuildFirstObjectionEmbedQo(
            proposal_title=dto.proposal_title,
            proposal_url=proposal_url,
            objector_id=dto.objector_id,
            objector_display_name=objector.display_name,
            objection_reason=dto.objection_reason,
            required_votes=dto.required_votes,
        )
        embed = ModerationEmbedBuilder.build_first_objection_embed(embed_qo)

        view = ObjectionCreationVoteView(self.bot)

        # 发送消息
        message = await self.bot.api_scheduler.submit(
            channel.send(embed=embed, view=view), priority=5
        )

        # 更新数据库中的 message_id
        await self.logic.update_vote_session_message_id(
            session_id=dto.vote_session_id, message_id=message.id
        )

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
