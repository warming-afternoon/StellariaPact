import logging
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from StellariaPact.cogs.Voting.dto import VoteDetailDto
from StellariaPact.cogs.Voting.views import VoteEmbedBuilder, VoteView
from StellariaPact.cogs.Voting.VotingLogic import VotingLogic
from StellariaPact.dto import ProposalDto, VoteSessionDto
from StellariaPact.services.VoteSessionService import VoteSessionService
from StellariaPact.share import (
    DiscordUtils,
    MissingRole,
    PermissionGuard,
    StellariaPactBot,
    StringUtils,
    UnitOfWork,
    safeDefer,
)
from StellariaPact.share.enums import VoteDuration

logger = logging.getLogger(__name__)


class Voting(commands.Cog):
    """
    处理所有与投票相关的命令和交互。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.logic = VotingLogic(bot)

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        """
        投票 Cog 的局部错误处理器
        """
        original_error = getattr(error, "original", error)

        if isinstance(original_error, MissingRole):
            if not interaction.response.is_done():
                await self.bot.api_scheduler.submit(
                    coro=interaction.response.send_message(str(original_error), ephemeral=True),
                    priority=1,
                )
        else:
            logger.error(f"在 Voting Cog 中发生未处理的错误: {error}", exc_info=True)
            if not interaction.response.is_done():
                await self.bot.api_scheduler.submit(
                    coro=interaction.response.send_message(
                        "发生了一个未知错误，请联系技术员", ephemeral=True
                    ),
                    priority=1,
                )

    @app_commands.command(name="刷新投票汇总面板", description="检查并修复当前帖子的投票汇总面板。若消息丢失则重新发送。")
    @app_commands.guild_only()
    async def refresh_vote_panel(self, interaction: discord.Interaction):
        await safeDefer(interaction, ephemeral=True)

        # 检查是否在讨论帖内
        if not isinstance(interaction.channel, discord.Thread):
            await self.bot.api_scheduler.submit(
                interaction.followup.send("此命令只能在讨论帖内使用。"), priority=1
            )
            return

        # 权限检查：限定提案人或管理组成员可以使用此命令
        can_manage = await PermissionGuard.can_manage_vote(interaction)
        if not can_manage:
            await self.bot.api_scheduler.submit(
                interaction.followup.send("你没有权限执行此操作。需为提案人或管理组成员。"), priority=1
            )
            return

        thread = interaction.channel

        async with UnitOfWork(self.bot.db_handler) as uow:
            # 获取关联的提案
            proposal = await uow.proposal.get_proposal_by_thread_id(thread.id)
            if not proposal:
                await self.bot.api_scheduler.submit(
                    interaction.followup.send("此帖子没有关联的提案，无法处理投票面板。"), priority=1
                )
                return

            # 查询本讨论帖对应 session_type=1 的 VoteSession 列表
            sessions = await uow.vote_session.get_all_sessions_in_thread_with_details(thread.id)
            type_1_sessions = [s for s in sessions if s.session_type == 1]

            if not type_1_sessions:
                # 场景 A: 本讨论帖对应 session_type=1 的 VoteSession 不存在
                # 派发创建事件，系统将自动创建 VoteSession、发送贴内面板及频道镜像
                proposal_dto = ProposalDto.model_validate(proposal)
                self.bot.dispatch(
                    "vote_session_created",
                    proposal_dto=proposal_dto,
                    options=[],  # 默认选项
                    duration_hours=VoteDuration.PROPOSAL_DEFAULT,
                    anonymous=True,
                    realtime=True,
                    notify=True,
                    create_in_voting_channel=True,
                    notify_creation_role=False,
                    thread=thread
                )
                await self.bot.api_scheduler.submit(
                    interaction.followup.send("未找到正式投票会话，正在初始化新的投票面板及镜像..."), priority=1
                )
                return

        # 场景 B: 若有，则拿最新的一个
        latest_session = max(type_1_sessions, key=lambda s: s.created_at)

        # 查询其对应消息能否获取到
        message_exists = False
        if latest_session.context_message_id:
            try:
                await thread.fetch_message(latest_session.context_message_id)
                message_exists = True
            except discord.NotFound:
                pass
            except discord.Forbidden:
                logger.warning(f"无法访问帖子 {thread.id} 的消息 {latest_session.context_message_id} (权限不足)")

        # 场景 B-1: 查询到则不做处理
        if message_exists:
            await self.bot.api_scheduler.submit(
                interaction.followup.send("当前投票汇总面板消息完好，无需处理。"), priority=1
            )
            return

        # 场景 B-2: 存在但对应消息不能获取到 (已丢失)
        # 汇总成 VoteDetailDto
        if latest_session.id is None:
            logger.error(f"投票会话 {latest_session} 的 ID 为 None，无法获取投票选项")
            await self.bot.api_scheduler.submit(
                interaction.followup.send("投票会话数据异常，无法处理。"), priority=1
            )
            return

        async with UnitOfWork(self.bot.db_handler) as uow:
            vote_options = await uow.vote_option.get_vote_options(latest_session.id)
            vote_details = VoteSessionService.get_vote_details_dto(latest_session, vote_options)
            await uow.commit()

        # 发送讨论帖内新的投票面板
        view = VoteView(self.bot)
        embeds = VoteEmbedBuilder.create_vote_panel_embed_v2(
            topic=proposal.title,
            vote_details=vote_details,
        )

        new_msg = await self.bot.api_scheduler.submit(
            thread.send(embeds=embeds, view=view), priority=5
        )

        async with UnitOfWork(self.bot.db_handler) as uow:
            # 更新 VoteSession.context_message_id 并提交数据库
            latest_session.context_message_id = new_msg.id
            uow.session.add(latest_session)
            await uow.commit()

        # 更新 DTO，并派发刷新事件以同步镜像（若镜像存在会被刷新显示为最新数据）
        vote_details.context_message_id = new_msg.id
        self.bot.dispatch("vote_details_updated", vote_details)

        await self.bot.api_scheduler.submit(
            interaction.followup.send("检测到面板消息丢失，已重新发送并刷新关联的镜像。"), priority=1
        )

    @commands.Cog.listener()
    async def on_vote_finished(self, session: "VoteSessionDto", result: "VoteDetailDto"):
        """
        监听通用投票结束事件，并发送最终结果。
        """
        try:
            thread = await DiscordUtils.fetch_thread(self.bot, session.context_thread_id)
            if not thread:
                logger.warning(f"无法为投票会话 {session.id} 找到有效的帖子。")
                return

            topic = StringUtils.clean_title(thread.name)

            jump_url = None
            if session.context_message_id:
                jump_url = f"https://discord.com/channels/{thread.guild.id}/{thread.id}/{session.context_message_id}"

            logger.info(f"投票会话 {session.id} 结束，生成跳转链接: {jump_url}")

            # 构建主结果 Embeds (包含普通投票和异议投票结果)
            result_embeds = VoteEmbedBuilder.build_vote_result_embeds(
                topic, result, jump_url=jump_url
            )

            all_embeds_to_send = result_embeds

            # 如果不是匿名投票，则构建并添加各选项的投票者名单
            if not result.is_anonymous and result.voters:
                voter_embeds = VoteEmbedBuilder.build_voter_list_embeds_from_details(result)
                all_embeds_to_send.extend(voter_embeds)

            # 准备要@的身份组
            content_to_send = ""
            if result.notify_flag:
                council_role_id = self.bot.config.get("roles", {}).get("councilModerator")
                auditor_role_id = self.bot.config.get("roles", {}).get("executionAuditor")
                mentions = []
                if council_role_id:
                    mentions.append(f"<@&{council_role_id}>")
                if auditor_role_id:
                    mentions.append(f"<@&{auditor_role_id}>")
                if mentions:
                    content_to_send = " ".join(mentions)

            # 分批发送所有 Embeds
            # Discord 一次最多发送 10 个 embeds
            for i in range(0, len(all_embeds_to_send), 10):
                chunk = all_embeds_to_send[i : i + 10]
                # 只在第一条消息中添加 content
                if i == 0 and content_to_send:
                    await self.bot.api_scheduler.submit(
                        thread.send(content=content_to_send, embeds=chunk),
                        priority=5,
                    )
                else:
                    await self.bot.api_scheduler.submit(
                        thread.send(embeds=chunk),
                        priority=5,
                    )
        except Exception as e:
            logger.error(
                f"处理 'on_vote_finished' 事件时出错 (会话ID: {session.id}): {e}",
                exc_info=True,
            )

    @commands.Cog.listener()
    async def on_vote_settings_changed(
        self,
        thread_id: int,
        message_id: int,
        vote_details: VoteDetailDto,
        operator: discord.User | discord.Member,
        reason: str,
        new_end_time: datetime | None = None,
        old_end_time: datetime | None = None,
    ):
        """
        监听投票设置变更事件，统一处理UI更新。
        """
        try:
            # 统一派发详情更新事件，让 on_vote_details_updated 处理所有面板更新
            self.bot.dispatch("vote_details_updated", vote_details)

            # 发送公开通知
            thread = await DiscordUtils.fetch_thread(self.bot, thread_id)
            if thread:
                notification_embed = VoteEmbedBuilder.create_settings_changed_notification_embed(
                    operator=operator,
                    reason=reason,
                    new_end_time=new_end_time,
                    old_end_time=old_end_time,
                )
                await self.bot.api_scheduler.submit(
                    thread.send(embed=notification_embed), priority=3
                )

        except Exception as e:
            logger.error(
                f"处理 'on_vote_settings_changed' 事件时出错 (消息ID: {message_id}): {e}",
                exc_info=True,
            )

    # -------------------------
    # 私有辅助方法
    # -------------------------

    async def _update_private_management_panel(
        self,
        interaction: discord.Interaction,
        thread_id: int,
        original_message_id: int,
        base_title: str = "投票管理",
        approve_text: str = "✅ 赞成",
        reject_text: str = "❌ 反对",
    ):
        """
        辅助方法，用于更新私有的投票管理面板
        """
        if not interaction.message:
            return

        try:
            panel_data = await self.logic.prepare_voting_choice_data(
                user_id=interaction.user.id,
                thread_id=thread_id,
                message_id=original_message_id,
            )
            jump_url = f"https://discord.com/channels/{panel_data.guild_id}/{panel_data.thread_id}/{panel_data.message_id}"
            embed = VoteEmbedBuilder.create_management_panel_embed(
                jump_url=jump_url,
                panel_data=panel_data,
                base_title=base_title,
                approve_text=approve_text,
                reject_text=reject_text,
            )
            await self.bot.api_scheduler.submit(interaction.edit_original_response(embed=embed), 1)
        except Exception as e:
            logger.warning(f"更新私有管理面板时出错: {e}")

    async def _update_formal_vote_panels(
        self,
        interaction: discord.Interaction,
        vote_details: VoteDetailDto,
        choice_text: str,
        thread_id: int,
    ):
        """
        在用户投票后，统一更新公开的投票面板和私有的管理面板
        """
        try:
            # 更新私有面板
            if vote_details.context_message_id:
                await self._update_private_management_panel(
                    interaction,
                    thread_id,
                    vote_details.context_message_id,
                    base_title="异议投票管理",
                    approve_text="✅ 同意异议",
                    reject_text="❌ 反对异议",
                )

            # 派发事件让中央监听器统一处理
            self.bot.dispatch("vote_details_updated", vote_details)
        except Exception as e:
            logger.error(f"更新投票面板时出错: {e}", exc_info=True)

    async def _update_thread_panel(self, thread: discord.Thread, vote_details: VoteDetailDto):
        """辅助方法：更新帖子内的投票面板。"""
        if not vote_details.context_message_id:
            return

        try:
            message = await thread.fetch_message(vote_details.context_message_id)

            clean_topic = StringUtils.clean_title(thread.name)
            new_embeds = VoteEmbedBuilder.create_vote_panel_embed_v2(
                topic=clean_topic,
                vote_details=vote_details,
            )

            if new_embeds:
                await self.bot.api_scheduler.submit(message.edit(embeds=new_embeds), priority=2)
        except discord.NotFound:
            logger.warning(f"找不到帖子内投票消息 {vote_details.context_message_id}，跳过更新。")
        except Exception as e:
            logger.error(f"更新帖子投票面板时出错: {e}", exc_info=True)

    async def _update_voting_channel_panel(
        self,
        channel: discord.TextChannel,
        thread: discord.Thread | None,
        vote_details: VoteDetailDto,
    ):
        """辅助方法：更新投票频道内的面板。"""
        if not vote_details.voting_channel_message_id:
            return

        try:
            message = await channel.fetch_message(vote_details.voting_channel_message_id)
            new_embed = None
            new_embeds = None

            if vote_details.objection_id:
                async with UnitOfWork(self.bot.db_handler) as uow:
                    objection_details = await uow.objection.get_objection_details_by_id(
                        vote_details.objection_id
                    )
                    if objection_details and thread:
                        new_embed = VoteEmbedBuilder.build_objection_voting_channel_embed(
                            objection=objection_details,
                            vote_details=vote_details,
                            thread_jump_url=thread.jump_url,
                        )
            else:
                async with UnitOfWork(self.bot.db_handler) as uow:
                    proposal = await uow.proposal.get_proposal_by_thread_id(
                        vote_details.context_thread_id
                    )
                    if proposal and thread:
                        proposal_dto = ProposalDto.model_validate(proposal)
                        new_embeds = VoteEmbedBuilder.build_voting_channel_embed(
                            proposal_dto, vote_details, thread.jump_url
                        )

            if new_embeds:
                await self.bot.api_scheduler.submit(message.edit(embeds=new_embeds), priority=2)
            elif new_embed:
                await self.bot.api_scheduler.submit(message.edit(embed=new_embed), priority=2)
        except discord.NotFound:
            logger.warning(
                f"找不到投票频道内消息 {vote_details.voting_channel_message_id}，跳过更新。"
            )
        except Exception as e:
            logger.error(f"更新投票频道面板时出错: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_vote_details_updated(self, vote_details: VoteDetailDto):
        """当投票详情更新时，同步所有相关的投票面板。"""
        try:
            if vote_details.context_message_id is None:
                return

            thread = await DiscordUtils.fetch_thread(self.bot, vote_details.context_thread_id)
            if not thread:
                logger.warning(
                    f"找不到投票 {vote_details.context_message_id} 所在的帖子，跳过更新。"
                )
                return

            await self._update_thread_panel(thread, vote_details)

            voting_channel_id_str = self.bot.config.get("channels", {}).get("voting_channel")
            if not voting_channel_id_str:
                return

            channel = await DiscordUtils.fetch_channel(self.bot, int(voting_channel_id_str))
            if not isinstance(channel, discord.TextChannel):
                logger.warning(f"投票频道 {voting_channel_id_str} 不是文本频道。")
                return

            await self._update_voting_channel_panel(channel, thread, vote_details)

        except Exception as e:
            logger.error(f"同步投票面板时出错: {e}", exc_info=True)
