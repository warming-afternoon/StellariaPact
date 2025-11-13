import logging
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands

from StellariaPact.cogs.Moderation.dto.HandleSupportObjectionResultDto import (
    HandleSupportObjectionResultDto,
)
from StellariaPact.cogs.Moderation.dto.ObjectionDetailsDto import ObjectionDetailsDto
from StellariaPact.cogs.Moderation.dto.ObjectionVotePanelDto import ObjectionVotePanelDto
from StellariaPact.cogs.Moderation.dto.ProposalDto import ProposalDto
from StellariaPact.cogs.Moderation.views.ObjectionCreationVoteView import ObjectionCreationVoteView
from StellariaPact.cogs.Voting.dto.VoteDetailDto import VoteDetailDto
from StellariaPact.cogs.Voting.qo.BuildFirstObjectionEmbedQo import BuildFirstObjectionEmbedQo
from StellariaPact.cogs.Voting.qo.CreateVoteSessionQo import CreateVoteSessionQo
from StellariaPact.cogs.Voting.views.ObjectionFormalVoteView import ObjectionFormalVoteView
from StellariaPact.cogs.Voting.views.ObjectionVoteEmbedBuilder import ObjectionVoteEmbedBuilder
from StellariaPact.cogs.Voting.views.VoteEmbedBuilder import VoteEmbedBuilder
from StellariaPact.cogs.Voting.views.VoteView import VoteView
from StellariaPact.cogs.Voting.views.VotingChannelView import VotingChannelView
from StellariaPact.cogs.Voting.VotingLogic import VotingLogic
from StellariaPact.share.DiscordUtils import DiscordUtils
from StellariaPact.share.enums.VoteDuration import VoteDuration
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.TimeUtils import TimeUtils
from StellariaPact.share.UnitOfWork import UnitOfWork

logger = logging.getLogger(__name__)


class ModerationEventListener(commands.Cog):
    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.logic: VotingLogic = VotingLogic(bot)

    @commands.Cog.listener()
    async def on_proposal_created(
        self,
        proposal_dto: ProposalDto,
        duration_hours: int = VoteDuration.PROPOSAL_DEFAULT,
        anonymous: bool = True,
        realtime: bool = True,
        notify: bool = True,
        create_in_voting_channel: bool = True,
        notify_creation_role: bool = True,
    ):
        """
        监听到提案成功创建的事件，为其创建投票面板，并尝试同步到投票频道
        采用两阶段提交模
        """
        logger.info(f"接收到 'proposal_created' 事件, 提案ID: {proposal_dto.id}")
        session_dto = None
        message = None
        thread = None
        end_time = None
        try:
            # --- 创建帖子内投票 ---
            if not proposal_dto.discussionThreadId:
                logger.warning(
                    f"提案 {proposal_dto.id} 没有关联的 discussionThreadId，无法创建投票面板。"
                )
                return

            thread = await DiscordUtils.fetch_thread(self.bot, proposal_dto.discussionThreadId)
            if not thread:
                logger.warning(
                    f"无法找到帖子 {proposal_dto.discussionThreadId}，"
                    f"无法为提案 {proposal_dto.id} 创建投票面板。"
                )
                return

            starter_message = thread.starter_message or await thread.fetch_message(thread.id)
            if not starter_message:
                logger.warning(
                    f"无法找到帖子 {proposal_dto.discussionThreadId} 的启动消息，"
                    "无法解析投票截止时间。"
                )
                return

            # 尝试从帖子内容中解析截止时间
            end_time = TimeUtils.parse_discord_timestamp(starter_message.content)

            # 如果解析出的时间已过期，则忽略它
            if end_time and end_time < datetime.now(timezone.utc):
                end_time = None

            # 如果没有有效的截止时间，则根据传入参数计算
            if end_time is None:
                target_tz = self.bot.config.get("timezone", "UTC")
                end_time = TimeUtils.get_utc_end_time(
                    duration_hours=duration_hours, target_tz=target_tz
                )

            # 创建投票面板
            view = VoteView(self.bot)
            embed = VoteEmbedBuilder.create_initial_vote_embed(
                topic=proposal_dto.title,
                author=None,
                realtime=realtime,
                anonymous=anonymous,
                notify_flag=notify,
                end_time=end_time,
            )
            message = await self.bot.api_scheduler.submit(
                thread.send(embed=embed, view=view), priority=5
            )

            # 创建投票会话记录
            async with UnitOfWork(self.bot.db_handler) as uow:
                qo = CreateVoteSessionQo(
                    thread_id=thread.id,
                    context_message_id=message.id,
                    realtime=realtime,
                    anonymous=anonymous,
                    notifyFlag=notify,
                    end_time=end_time,
                )
                session_dto = await uow.voting.create_vote_session(qo)
                await uow.commit()

            logger.debug(f"成功为提案 {proposal_dto.id} 创建了核心投票会话 {session_dto.id}。")

        except Exception as e:
            logger.error(
                f"为提案 {proposal_dto.id} 创建核心投票面板时发生错误: {e}", exc_info=True
            )
            return

        # --- 创建投票频道镜像 ---
        if not (create_in_voting_channel and session_dto and message and thread and end_time):
            return

        try:
            voting_channel_id_str = self.bot.config.get("channels", {}).get("voting_channel")
            if voting_channel_id_str:
                voting_channel = await DiscordUtils.fetch_channel(
                    self.bot, int(voting_channel_id_str)
                )
                if isinstance(voting_channel, discord.TextChannel):
                    # 创建一个临时的、初始状态的 VoteDetailDto
                    initial_vote_details = VoteDetailDto(
                        context_thread_id=thread.id,
                        objection_id=None,
                        voting_channel_message_id=None,
                        is_anonymous=anonymous,
                        realtime_flag=realtime,
                        notify_flag=notify,
                        end_time=end_time,
                        context_message_id=message.id,
                        status=1,
                        total_votes=0,
                        approve_votes=0,
                        reject_votes=0,
                        voters=[],
                    )

                    channel_view = VotingChannelView(self.bot)
                    channel_embed = VoteEmbedBuilder.build_voting_channel_embed(
                        proposal=proposal_dto,
                        vote_details=initial_vote_details,
                        thread_jump_url=thread.jump_url,
                    )

                    # 准备 @ 投票创建 身份组
                    content_to_send = None
                    if notify_creation_role:
                        role_id = self.bot.config.get("roles", {}).get("voteCreationNotifier")
                        if role_id:
                            content_to_send = f"<@&{role_id}>"

                    voting_channel_message = await self.bot.api_scheduler.submit(
                        voting_channel.send(content=content_to_send, embed=channel_embed, view=channel_view), priority=4
                    )

                    # 更新数据库
                    async with UnitOfWork(self.bot.db_handler) as uow:
                        await uow.voting.update_voting_channel_message_id(
                            session_dto.id, voting_channel_message.id
                        )
                        await uow.commit()

                    logger.debug(
                        f"成功为会话 {session_dto.id} 创建并关联了镜像投票，"
                        f"消息ID: {voting_channel_message.id}"
                    )
                else:
                    logger.warning("配置的 voting_channel 不是一个有效的文本频道。")
            else:
                logger.debug("未配置 voting_channel，跳过创建镜像投票。")
        except Exception as e:
            logger.error(
                f"为会话 {session_dto.id} 创建镜像投票时发生非致命错误: {e}", exc_info=True
            )

    @commands.Cog.listener()
    async def on_objection_thread_created(
        self, thread: discord.Thread, objection_dto: ObjectionDetailsDto
    ):
        """
        监听到异议帖成功创建的事件，为其创建投票面板，并随后同步到投票频道。
        采用两阶段提交模式
        """
        logger.info(
            f"接收到 'objection_thread_created' 事件，"
            f"在新异议帖 '{thread.name}' (ID: {thread.id}) 中创建投票面板。"
        )
        session_dto = None
        try:
            # 计算结束时间
            end_time = datetime.now(timezone.utc) + timedelta(hours=VoteDuration.OBJECTION_DEFAULT)

            # 创建帖子内的投票面板
            view_in_thread = ObjectionFormalVoteView(self.bot)
            embed_in_thread = ObjectionVoteEmbedBuilder.create_formal_embed(
                objection_dto=objection_dto, end_time=end_time
            )
            message_in_thread = await self.bot.api_scheduler.submit(
                thread.send(embed=embed_in_thread, view=view_in_thread), priority=2
            )

            # 创建核心投票会话
            async with UnitOfWork(self.bot.db_handler) as uow:
                qo = CreateVoteSessionQo(
                    thread_id=thread.id,
                    objection_id=objection_dto.objection_id,
                    context_message_id=message_in_thread.id,
                    realtime=True,
                    anonymous=True,
                    end_time=end_time,
                )
                session_dto = await uow.voting.create_vote_session(qo)
                await uow.commit()

            logger.debug(
                f"成功为异议 {objection_dto.objection_id} 创建了核心投票会话 {session_dto.id}。"
            )

        except Exception as e:
            logger.error(f"无法在异议帖 {thread.id} 中创建核心投票面板: {e}", exc_info=True)
            return  # 如果核心功能失败，则直接返回

        # 尝试创建并关联投票频道的镜像
        # 这是一个独立的try-except块，它的失败不应影响主流程
        if not session_dto:
            return

        try:
            voting_channel_id_str = self.bot.config.get("channels", {}).get("voting_channel")
            if voting_channel_id_str:
                voting_channel = await DiscordUtils.fetch_channel(
                    self.bot, int(voting_channel_id_str)
                )
                if isinstance(voting_channel, discord.TextChannel):
                    initial_vote_details = VoteDetailDto(
                        context_thread_id=thread.id,
                        objection_id=objection_dto.objection_id,
                        voting_channel_message_id=None,
                        is_anonymous=True,
                        realtime_flag=True,
                        notify_flag=True,
                        end_time=end_time,
                        context_message_id=message_in_thread.id,
                        status=1,
                        total_votes=0,
                        approve_votes=0,
                        reject_votes=0,
                        voters=[],
                    )
                    channel_view = VotingChannelView(self.bot)
                    channel_embed = VoteEmbedBuilder.build_objection_voting_channel_embed(
                        objection=objection_dto,
                        vote_details=initial_vote_details,
                        thread_jump_url=thread.jump_url,
                    )

                    voting_channel_message = await self.bot.api_scheduler.submit(
                        voting_channel.send(embed=channel_embed, view=channel_view), priority=4
                    )

                    # 更新数据库
                    async with UnitOfWork(self.bot.db_handler) as uow:
                        await uow.voting.update_voting_channel_message_id(
                            session_dto.id, voting_channel_message.id
                        )
                        await uow.commit()
                    logger.debug(f"成功为异议会话 {session_dto.id} 创建并关联了镜像投票")
        except Exception as e:
            logger.error(
                f"为异议会话 {session_dto.id} 创建镜像投票时发生非致命错误: {e}", exc_info=True
            )

    @commands.Cog.listener()
    async def on_create_objection_vote_panel(
        self, dto: ObjectionVotePanelDto, interaction: discord.Interaction | None = None
    ):
        """监听创建异议投票面板的请求"""
        logger.info(
            f"Received request to create objection vote panel for objection {dto.objection_id}"
        )
        try:
            # 获取频道
            channel_id_str = self.bot.config.get("channels", {}).get("objection_publicity")
            guild_id_str = self.bot.config.get("guild_id")
            guild = (
                interaction.guild
                if interaction and interaction.guild
                else self.bot.get_guild(int(guild_id_str if guild_id_str else 0))
            )

            if not channel_id_str or not guild:
                raise RuntimeError(
                    "Publicity channel or server ID is not configured, or server information"
                    " cannot be obtained."
                )

            channel = await DiscordUtils.fetch_channel(self.bot, int(channel_id_str))

            if not isinstance(channel, discord.TextChannel):
                raise RuntimeError(
                    f"Objection publicity channel (ID: {channel_id_str}) must be a text channel."
                )

            # 构建 Embed 和 View
            objector = await self.bot.fetch_user(dto.objector_id)

            embed_qo = BuildFirstObjectionEmbedQo(
                proposal_title=dto.proposal_title,
                proposal_url=f"https://discord.com/channels/{guild.id}/{dto.proposal_thread_id}",
                objector_id=dto.objector_id,
                objector_display_name=objector.display_name,
                objection_reason=dto.objection_reason,
                required_votes=dto.required_votes,
            )
            embed = ObjectionVoteEmbedBuilder.build_first_objection_embed(qo=embed_qo)
            view = ObjectionCreationVoteView(self.bot)

            message = await channel.send(embed=embed, view=view)

            await self.logic.update_vote_session_message_id(dto.vote_session_id, message.id)

        except Exception as e:
            logger.error(
                f"Error creating objection vote panel for objection {dto.objection_id}: {e}",
                exc_info=True,
            )

    @commands.Cog.listener()
    async def on_update_objection_vote_panel(
        self, message: discord.Message, result_dto: HandleSupportObjectionResultDto
    ):
        """监听更新异议投票面板的请求"""

        try:
            original_embed = message.embeds[0]
            if not message.guild:
                raise RuntimeError("Message does not have guild information.")

            guild_id = message.guild.id

            if result_dto.is_goal_reached:
                # 目标达成，更新Embed为“完成”状态，并禁用按钮
                new_embed = ObjectionVoteEmbedBuilder.create_goal_reached_embed(
                    original_embed, result_dto, guild_id
                )
                # 创建一个新的、禁用了按钮的视图
                disabled_view = ObjectionCreationVoteView(self.bot)
                for item in disabled_view.children:
                    if isinstance(item, discord.ui.Button):
                        item.disabled = True

                await self.bot.api_scheduler.submit(
                    message.edit(embed=new_embed, view=disabled_view), 2
                )
            else:
                # 目标未达成，只更新支持数
                new_embed = ObjectionVoteEmbedBuilder.update_support_embed(
                    original_embed, result_dto, guild_id
                )
                await self.bot.api_scheduler.submit(message.edit(embed=new_embed), 2)
        except Exception as e:
            logger.error(
                f"Error updating objection vote panel for message {message.id}: {e}",
                exc_info=True,
            )


async def setup(bot: StellariaPactBot):
    await bot.add_cog(ModerationEventListener(bot))
