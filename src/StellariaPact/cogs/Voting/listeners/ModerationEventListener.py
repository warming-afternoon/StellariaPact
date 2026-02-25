import logging
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands

from StellariaPact.cogs.Voting.dto import OptionResult, VoteDetailDto
from StellariaPact.cogs.Voting.qo import BuildFirstObjectionEmbedQo, CreateVoteSessionQo
from StellariaPact.cogs.Voting.views import (
    ObjectionCreationVoteView,
    ObjectionFormalVoteView,
    ObjectionVoteEmbedBuilder,
    VoteEmbedBuilder,
    VoteView,
    VotingChannelView,
)
from StellariaPact.cogs.Voting.VotingLogic import VotingLogic
from StellariaPact.dto import (
    HandleSupportObjectionResultDto,
    ObjectionDetailsDto,
    ObjectionVotePanelDto,
    ProposalDto,
)
from StellariaPact.share import DiscordUtils, StellariaPactBot, TimeUtils, UnitOfWork
from StellariaPact.share.enums.VoteDuration import VoteDuration

logger = logging.getLogger(__name__)


class ModerationEventListener(commands.Cog):
    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.logic: VotingLogic = VotingLogic(bot)

    @commands.Cog.listener()
    async def on_vote_session_created(
        self,
        proposal_dto: ProposalDto,
        options: list[str],
        duration_hours: int,
        anonymous: bool,
        realtime: bool,
        notify: bool,
        create_in_voting_channel: bool,
        notify_creation_role: bool,
        thread: discord.Thread,
    ):
        """
        为提案讨论帖创建投票面板，并尝试同步到投票频道
        采用两阶段提交模式
        """
        logger.info(f"接收到 'vote_session_created' 事件, 提案ID: {proposal_dto.id}")

        # 第一阶段：在讨论帖内创建核心投票面板
        try:
            vote_details = await self._create_in_thread_vote(
                proposal_dto, thread, duration_hours, anonymous, realtime, notify, options
            )
        except Exception as e:
            logger.error(
                f"为提案 {proposal_dto.id} 创建核心投票面板时发生错误: {e}", exc_info=True
            )
            return

        # 检查是否需要创建投票频道镜像，以及第一阶段是否成功
        if not (create_in_voting_channel and vote_details and vote_details.context_message_id):
            return

        # 第二阶段：在投票频道创建镜像投票面板
        try:
            await self._create_voting_channel_mirror(
                proposal_dto,
                thread,
                vote_details,
                notify_creation_role,
            )
        except Exception as e:
            logger.error(
                f"为上下文消息 {vote_details.context_message_id} 创建镜像投票时发生非致命错误: {e}",
                exc_info=True,
            )

    async def _create_in_thread_vote(
        self,
        proposal_dto: ProposalDto,
        thread: discord.Thread,
        duration_hours: int,
        anonymous: bool,
        realtime: bool,
        notify: bool,
        options: list[str],
    ):
        """
        在讨论帖内创建核心投票面板并保存到数据库

        Args:
            proposal_dto: 提案数据对象
            thread: Discord 讨论帖对象
            duration_hours: 投票持续时间（小时）
            anonymous: 是否匿名投票
            realtime: 是否实时更新
            notify: 是否通知
            options: 投票选项列表

        Returns:
            VoteDetailDto | None: 初始化后的投票详情；失败时返回 None。
        """
        if not proposal_dto.discussion_thread_id:
            logger.warning(
                f"提案 {proposal_dto.id} 没有关联的 discussion_thread_id，无法创建投票面板。"
            )
            return None

        starter_message = thread.starter_message or await thread.fetch_message(thread.id)
        if not starter_message:
            logger.warning(
                f"无法找到帖子 {proposal_dto.discussion_thread_id} 的启动消息，"
                f"无法解析投票截止时间。"
            )
            return None

        end_time = TimeUtils.parse_discord_timestamp(starter_message.content)
        if end_time and end_time < datetime.now(timezone.utc).replace(tzinfo=None):
            end_time = None

        if end_time is None:
            target_tz = self.bot.config.get("timezone", "UTC")
            end_time = TimeUtils.get_utc_end_time(
                duration_hours=duration_hours, target_tz=target_tz
            )

        # 初始选项规则：若用户未传入 options，则使用默认项“支持提案”；否则使用用户传入项
        all_option_texts = options if options else ["支持提案"]
        total_choices = len(all_option_texts)

        async with UnitOfWork(self.bot.db_handler) as uow:
            qo = CreateVoteSessionQo(
                guild_id=thread.guild.id,
                thread_id=thread.id,
                proposal_id=proposal_dto.id,
                context_message_id=0,  # 占位，后续更新
                realtime=realtime,
                anonymous=anonymous,
                notify_flag=notify,
                end_time=end_time,
                total_choices=total_choices,
            )
            session_dto = await uow.vote_session.create_vote_session(qo)
            if not session_dto.id:
                raise ValueError("创建投票会话后未能获取ID")

            # 创建所有选项 (普通投票选项，option_type=0)
            await uow.vote_option.create_vote_options(
                session_dto.id, all_option_texts, option_type=0
            )
            await uow.commit()

            # 从数据库查询刚创建的选项，构建 VoteDetailDto
            vote_options = await uow.vote_option.get_vote_options(session_dto.id)
            vote_details_options = [
                OptionResult(
                    choice_index=opt.choice_index,
                    choice_text=opt.choice_text,
                    approve_votes=0,
                    reject_votes=0,
                    total_votes=0,
                )
                for opt in vote_options
                if opt.option_type == 0
            ]

            initial_vote_details = VoteDetailDto(
                guild_id=thread.guild.id,
                context_thread_id=thread.id,
                objection_id=None,
                voting_channel_message_id=None,
                is_anonymous=anonymous,
                realtime_flag=realtime,
                notify_flag=notify,
                end_time=end_time,
                context_message_id=None,
                status=1, # 投票状态 1-进行中
                total_choices=total_choices,
                options=vote_details_options,
                normal_options=vote_details_options,
                voters=[],
            )

            view = VoteView(self.bot)
            embeds = VoteEmbedBuilder.create_vote_panel_embed_v2(
                topic=proposal_dto.title,
                vote_details=initial_vote_details,
            )
            message = await self.bot.api_scheduler.submit(
                thread.send(embeds=embeds, view=view), priority=5
            )

            # 更新消息ID
            await uow.vote_session.update_vote_session_message_id(
                session_dto.id, message.id
            )
            await uow.commit()

        initial_vote_details.context_message_id = message.id
        logger.debug(f"成功为提案 {proposal_dto.id} 创建了核心投票会话 {session_dto.id}")
        return initial_vote_details

    async def _create_voting_channel_mirror(
        self,
        proposal_dto: ProposalDto,
        thread: discord.Thread,
        vote_details: VoteDetailDto,
        notify_creation_role: bool,
    ):
        """
        在投票频道创建镜像投票面板并关联到数据库

        Args:
            proposal_dto: 提案数据对象
            session_dto: 投票会话数据对象
            message: 帖子内的投票消息对象
            thread: Discord 讨论帖对象
            vote_details: 线程内投票面板对应的投票详情
            notify_creation_role: 是否通知创建角色
        """
        voting_channel_id_str = self.bot.config.get("channels", {}).get("voting_channel")
        if not voting_channel_id_str:
            logger.debug("未配置 voting_channel，跳过创建镜像投票。")
            return

        voting_channel = await DiscordUtils.fetch_channel(self.bot, int(voting_channel_id_str))
        if not isinstance(voting_channel, discord.TextChannel):
            logger.warning("配置的 voting_channel 不是一个有效的文本频道。")
            return

        async with UnitOfWork(self.bot.db_handler) as uow:
            context_message_id = vote_details.context_message_id
            if not context_message_id:
                logger.warning("vote_details 缺少 context_message_id，跳过创建镜像投票。")
                return

            session = await uow.vote_session.get_vote_session_by_context_message_id(context_message_id)
            if not session:
                logger.warning(
                    f"未找到 context_message_id={context_message_id} 对应的投票会话，跳过创建镜像投票。"
                )
                return

            channel_view = VotingChannelView(self.bot)
            channel_embeds = VoteEmbedBuilder.build_voting_channel_embed(
                proposal=proposal_dto,
                vote_details=vote_details,
                thread_jump_url=thread.jump_url,
            )

            content_to_send = None
            if notify_creation_role:
                role_id = self.bot.config.get("roles", {}).get("voteCreationNotifier")
                if role_id:
                    content_to_send = f"<@&{role_id}>"

            voting_channel_message = await self.bot.api_scheduler.submit(
                voting_channel.send(content=content_to_send, embeds=channel_embeds, view=channel_view),
                priority=4,
            )

            if not session.id:
                logger.warning(
                    f"context_message_id={context_message_id} 对应会话缺少ID，跳过镜像消息关联。"
                )
                return

            await uow.vote_session.update_voting_channel_message_id(
                session.id, voting_channel_message.id
            )
            await uow.commit()

        logger.debug(f"成功为会话 {session.id} 创建并关联了镜像投票")

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
        message_in_thread = None
        end_time = None
        try:
            # 计算结束时间
            end_time = datetime.now(timezone.utc) + timedelta(hours=VoteDuration.OBJECTION_DEFAULT)

            # 为初始 Embed 创建一个临时的 VoteDetailDto
            initial_vote_details = VoteDetailDto(
                guild_id=thread.guild.id,
                context_thread_id=thread.id,
                objection_id=objection_dto.objection_id,
                voting_channel_message_id=None,
                is_anonymous=True,
                realtime_flag=True,
                notify_flag=True,
                end_time=end_time,
                context_message_id=None,  # 此时消息还未发送
                status=1,
                total_choices=1,
                options=[
                    OptionResult(
                        choice_index=1,
                        choice_text="同意异议",
                        approve_votes=0,
                        reject_votes=0,
                        total_votes=0,
                    )
                ],
                voters=[],
            )

            # 创建帖子内的投票面板
            view_in_thread = ObjectionFormalVoteView(self.bot)
            embed_in_thread = ObjectionVoteEmbedBuilder.create_formal_embed(
                objection_dto=objection_dto, vote_details=initial_vote_details
            )
            message_in_thread = await self.bot.api_scheduler.submit(
                thread.send(embed=embed_in_thread, view=view_in_thread), priority=2
            )

            # 创建核心投票会话
            async with UnitOfWork(self.bot.db_handler) as uow:
                qo = CreateVoteSessionQo(
                    guild_id=thread.guild.id,
                    thread_id=thread.id,
                    objection_id=objection_dto.objection_id,
                    proposal_id=objection_dto.proposal_id,
                    context_message_id=message_in_thread.id,
                    realtime=True,
                    anonymous=True,
                    end_time=end_time,
                    total_choices=1,
                )
                session_dto = await uow.vote_session.create_vote_session(qo)
                if not session_dto.id:
                    raise ValueError("创建异议投票会话后未能获取ID")

                # 为异议票创建默认的单选项（option_type=1）
                await uow.vote_option.create_vote_options(
                    session_dto.id, ["同意异议"], option_type=1
                )
                await uow.commit()

            logger.debug(
                f"成功为异议 {objection_dto.objection_id} 创建了核心投票会话 {session_dto.id}。"
            )

        except Exception as e:
            logger.error(f"无法在异议帖 {thread.id} 中创建核心投票面板: {e}", exc_info=True)
            return  # 如果核心功能失败，则直接返回

        # 尝试创建并关联投票频道的镜像
        if not session_dto or not message_in_thread or not end_time:
            return

        try:
            voting_channel_id_str = self.bot.config.get("channels", {}).get("voting_channel")
            if not voting_channel_id_str:
                return

            voting_channel = await DiscordUtils.fetch_channel(self.bot, int(voting_channel_id_str))
            if not isinstance(voting_channel, discord.TextChannel):
                return

            initial_vote_details = VoteDetailDto(
                guild_id=thread.guild.id,
                context_thread_id=thread.id,
                objection_id=objection_dto.objection_id,
                voting_channel_message_id=None,
                is_anonymous=True,
                realtime_flag=True,
                notify_flag=True,
                end_time=end_time,
                context_message_id=message_in_thread.id,
                status=1,
                total_choices=1,
                options=[
                    OptionResult(
                        choice_index=1,
                        choice_text="同意异议",
                        approve_votes=0,
                        reject_votes=0,
                        total_votes=0,
                    )
                ],
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
                await uow.vote_session.update_voting_channel_message_id(
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
