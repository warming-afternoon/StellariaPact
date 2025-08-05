import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from StellariaPact.cogs.Moderation.dto.HandleSupportObjectionResultDto import (
    HandleSupportObjectionResultDto,
)
from StellariaPact.cogs.Moderation.dto.RaiseObjectionResultDto import (
    RaiseObjectionResultDto,
)
from StellariaPact.cogs.Moderation.logic.ModerationLogic import ModerationLogic
from StellariaPact.cogs.Moderation.qo.BuildAdminReviewEmbedQo import (
    BuildAdminReviewEmbedQo,
)
from StellariaPact.cogs.Moderation.qo.BuildConfirmationEmbedQo import (
    BuildConfirmationEmbedQo,
)
from StellariaPact.cogs.Moderation.views.AbandonReasonModal import (
    AbandonReasonModal,
)
from StellariaPact.cogs.Moderation.views.ConfirmationView import ConfirmationView
from StellariaPact.cogs.Moderation.views.ModerationEmbedBuilder import (
    ModerationEmbedBuilder,
)
from StellariaPact.cogs.Moderation.views.ObjectionAdminReviewView import (
    ObjectionAdminReviewView,
)
from StellariaPact.cogs.Moderation.views.ObjectionCreationVoteView import (
    ObjectionCreationVoteView,
)
from StellariaPact.cogs.Moderation.views.ObjectionModal import ObjectionModal
from StellariaPact.cogs.Moderation.views.ReasonModal import ReasonModal
from StellariaPact.cogs.Voting.dto.VoteSessionDto import VoteSessionDto
from StellariaPact.cogs.Voting.dto.VoteStatusDto import VoteStatusDto
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
        self.kick_proposal_context_menu = app_commands.ContextMenu(
            name="踢出提案", callback=self.kick_proposal, type=discord.AppCommandType.message
        )

    def cog_load(self) -> None:
        """在 Cog 被添加到 Bot 后，进行依赖注入和初始化。"""
        self.logic: ModerationLogic = ModerationLogic(self.bot)
        self.bot.tree.add_command(self.kick_proposal_context_menu)
        # 注册持久化视图
        self.bot.add_view(ObjectionCreationVoteView(self.bot, self.logic))
        # logger.info("已注册 ObjectionCreationVoteView 作为持久化视图。")

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
                # 1. 确定目标帖子ID
                target_thread_id = self._determine_target_thread_id(interaction, proposal_link)

                # 2. 调用 Logic 层完成数据库操作
                result_dto = await self.logic.handle_raise_objection(
                    user_id=interaction.user.id,
                    target_thread_id=target_thread_id,
                    reason=reason,
                )

                # --- 阶段二: 与 Discord API 交互并更新 ---
                if result_dto.is_first_objection:
                    await self._handle_first_objection_ui(interaction, result_dto)
                else:
                    await self._handle_subsequent_objection_ui(interaction, result_dto)

                # --- 最终确认 ---
                final_message = (
                    "异议已成功发起！\n由于为首次异议，将直接在公示频道开启异议产生票收集。"
                    if result_dto.is_first_objection
                    else "异议已成功发起！\n由于该提案已有其他异议，本次异议需要先由管理员审核。"
                )
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

    async def _handle_first_objection_ui(
        self, interaction: discord.Interaction, result_dto: RaiseObjectionResultDto
    ):
        """处理首次异议的UI交互（发送投票面板）。"""
        # 1. 获取频道
        channel_id_str = self.bot.config.get("channels", {}).get("objection_publicity")
        if not channel_id_str or not interaction.guild:
            raise RuntimeError("公示频道未配置或无法获取服务器信息。")
        channel = await self._fetch_channel(int(channel_id_str))

        # 类型守卫，确保公示频道是文本频道
        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError(f"异议公示频道 (ID: {channel_id_str}) 必须是一个文本频道。")

        # 2. 构建 Embed 和 View
        objector = await self.bot.fetch_user(result_dto.objector_id)
        guild_id = self.bot.config.get("guild_id")
        if not guild_id:
            raise RuntimeError("Guild ID 未配置。")
        proposal_url = f"https://discord.com/channels/{guild_id}/{result_dto.proposal_thread_id}"

        embed = discord.Embed(
            title="异议产生票收集中",
            description=(
                f"对提案 **[{result_dto.proposal_title}]({proposal_url})** 的一项异议"
                "需要收集足够的支持票以进入正式投票阶段。\n\n"
                f"**提案者**: <@{result_dto.objector_id}> ({objector.display_name})"
            ),
            color=discord.Color.yellow(),
        )
        embed.add_field(name="异议理由", value=f"{result_dto.objection_reason}", inline=False)
        embed.add_field(name="所需票数", value=str(result_dto.required_votes), inline=True)
        embed.add_field(name="当前支持", value=f"0 / {result_dto.required_votes}", inline=True)

        # 创建一个用于本次消息的视图实例
        view = ObjectionCreationVoteView(self.bot, self.logic)

        # 3. 发送消息
        message = await self.bot.api_scheduler.submit(
            channel.send(embed=embed, view=view), priority=5
        )

        # 4. 更新数据库中的 message_id
        await self.logic.update_vote_session_message_id(
            session_id=result_dto.vote_session_id, message_id=message.id
        )

    async def _handle_subsequent_objection_ui(
        self, interaction: discord.Interaction, result_dto: RaiseObjectionResultDto
    ):
        """处理后续异议的UI交互（发送审核面板）。"""
        # 1. 获取频道
        channel_id_str = self.bot.config.get("channels", {}).get("objection_audit")
        if not channel_id_str:
            raise RuntimeError("审核频道未配置")
        if not self.bot.user:
            raise RuntimeError("机器人未登录")
        channel = await self._fetch_channel(int(channel_id_str))

        if not isinstance(channel, discord.ForumChannel):
            raise RuntimeError(f"审核频道 (ID: {channel.id}) 不是一个论坛频道。")

        # 2. 构建 Embed 和 View
        guild_id = self.bot.config.get("guild_id")
        if not guild_id:
            raise RuntimeError("Guild ID 未配置。")

        embed_qo = BuildAdminReviewEmbedQo(
            objection_id=result_dto.objection_id,
            objector_id=result_dto.objector_id,
            objection_reason=result_dto.objection_reason,
            proposal_id=result_dto.proposal_id,
            proposal_title=result_dto.proposal_title,
            proposal_thread_id=result_dto.proposal_thread_id,
            guild_id=int(guild_id),
        )
        embed = ModerationEmbedBuilder.build_admin_review_embed(embed_qo, self.bot.user)
        view = ObjectionAdminReviewView(self.bot, result_dto.objection_id)

        # 3. 在论坛频道中创建审核帖子
        thread_name = f"异议审核 - {result_dto.proposal_title[:50]}"
        thread_with_message = await self.bot.api_scheduler.submit(
            channel.create_thread(name=thread_name, embed=embed, view=view), priority=3
        )
        thread = thread_with_message[0]

        # 4. 更新数据库中的审核帖子ID
        async with UnitOfWork(self.bot.db_handler) as uow:
            await uow.moderation.update_objection_review_thread_id(
                result_dto.objection_id, thread.id
            )
            await uow.commit()

    async def _fetch_channel(self, channel_id: int) -> discord.TextChannel | discord.ForumChannel:
        """安全地获取一个频道，优先使用缓存，支持文本和论坛频道。"""
        channel = self.bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden) as e:
                raise RuntimeError(f"无法获取ID为 {channel_id} 的频道。") from e

        if not isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
            raise RuntimeError(f"ID {channel_id} 不是一个文本或论坛频道。")
        return channel

    async def _fetch_thread(self, thread_id: int) -> Optional[discord.Thread]:
        """安全地获取一个帖子，优先使用缓存。"""
        thread = self.bot.get_channel(thread_id)
        if isinstance(thread, discord.Thread):
            return thread
        try:
            thread = await self.bot.fetch_channel(thread_id)
            if isinstance(thread, discord.Thread):
                return thread
            return None
        except (discord.NotFound, discord.Forbidden):
            logger.warning(f"无法获取ID为 {thread_id} 的帖子。")
            return None

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
            result = await self.logic.handle_objection_vote_finished(session_dto, result_dto)

            if not result:
                logger.warning(
                    f"处理异议投票结束事件 (异议ID: {session_dto.objectionId}) 未返回有效结果。"
                )
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
                    return  # 成功编辑后即可返回
                except discord.NotFound:
                    logger.warning(f"无法找到原始投票消息 {result.message_id}，将发送新消息。")
                except Exception as e:
                    logger.error(
                        f"更新原始投票消息 {result.message_id} 时出错: {e}", exc_info=True
                    )

            # 如果编辑失败或没有 message_id，则发送新消息
            await self.bot.api_scheduler.submit(channel.send(embed=embed), priority=5)

        except Exception as e:
            logger.error(f"在 on_objection_vote_finished 中发生意外错误: {e}", exc_info=True)

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

            discussion_channel = await self._fetch_channel(int(discussion_channel_id_str))
            if not isinstance(discussion_channel, discord.ForumChannel):
                raise RuntimeError("提案讨论频道必须是论坛频道。")

            #  构建帖子内容
            thread_name = f"异议 - {result_dto.proposal_title}"
            content = (
                f"**关联提案**: <#{result_dto.proposal_discussion_thread_id}>\n"
                f"**异议发起人**: <@{result_dto.objector_id}>\n\n"
                f"**理由**:\n{result_dto.objection_reason}\n\n"
                f"现在，请就此异议进行正式投票。\n如果赞成票多于反对票，原提案将被推翻。"
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

            # 4. 更新数据库和原提案
            assert result_dto.objection_id is not None, "Objection ID is required"
            assert (
                result_dto.proposal_discussion_thread_id is not None
            ), "Original proposal thread ID is required"
            await self.logic.handle_objection_thread_creation(
                objection_id=result_dto.objection_id,
                objection_thread_id=objection_thread.id,
                original_proposal_thread_id=result_dto.proposal_discussion_thread_id,
            )

            # 5. 更新原提案帖的标签和标题
            original_thread = await self._fetch_thread(result_dto.proposal_discussion_thread_id)
            if original_thread:
                # 类型守卫，确保父频道是论坛
                if not isinstance(original_thread.parent, discord.ForumChannel):
                    logger.warning(f"帖子 {original_thread.id} 的父频道不是论坛，无法修改标签。")
                    return

                frozen_tag_id = self.bot.config.get("tags", {}).get("frozen")
                if not frozen_tag_id:
                    logger.warning("未在 config.json 中配置 'frozen' 标签ID。")
                    return

                # 获取冻结标签对象
                frozen_tag = original_thread.parent.get_tag(int(frozen_tag_id))
                if not frozen_tag:
                    logger.warning(
                        f"在论坛频道 {original_thread.parent.name} 中"
                        f"找不到ID为 {frozen_tag_id} 的标签"
                    )
                    return

                # 准备新标题和新标签
                if not result_dto.proposal_title:
                    logger.warning(f"提案 {result_dto.proposal_id} 缺少标题，无法更新。")
                    return
                clean_title = StringUtils.clean_title(result_dto.proposal_title)
                new_title = f"[冻结中] {clean_title}"

                # 为保证幂等性，移除可能存在的其他状态标签，然后应用新标签
                # 注意：这里需要一个更健壮的方法来移除所有“状态类”标签
                current_tags = original_thread.applied_tags
                new_tags = [t for t in current_tags if t.id != frozen_tag.id]
                new_tags.append(frozen_tag)

                await self.bot.api_scheduler.submit(
                    original_thread.edit(name=new_title, applied_tags=new_tags),
                    priority=4,
                )
                logger.info(f"已将原提案帖 {original_thread.id} 的标题和标签更新为“冻结中”。")

        except (RuntimeError, ValueError) as e:
            logger.error(f"处理 on_objection_goal_reached 事件时出错: {e}")
        except Exception as e:
            logger.error(f"处理 on_objection_goal_reached 事件时发生意外错误: {e}", exc_info=True)
