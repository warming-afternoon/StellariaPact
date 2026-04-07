import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

from StellariaPact.cogs.Voting.dto import OptionResult, VoteDetailDto
from StellariaPact.cogs.Voting.qo import CreateVoteSessionQo
from StellariaPact.cogs.Voting.views import VoteEmbedBuilder, VoteView, VotingChannelView
from StellariaPact.cogs.Voting.VotingLogic import VotingLogic
from StellariaPact.dto import ProposalDto
from StellariaPact.share import DiscordUtils, StellariaPactBot, TimeUtils, UnitOfWork

logger = logging.getLogger(__name__)


class ModerationEventListener(commands.Cog):
    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.logic: VotingLogic = VotingLogic(bot)

    @commands.Cog.listener()
    async def on_vote_session_created(
        self,
        proposal_dto: ProposalDto,
        options: list[str], # 投票选项
        duration_hours: int, # 投票时长
        anonymous: bool, # 是否匿名投票
        realtime: bool, # 是否实时更新
        notify: bool, # 是否通知
        create_in_voting_channel: bool, # 是否在投票频道创建
        notify_creation_role: bool, # 是否通知创建角色
        thread: discord.Thread, # 讨论帖
        max_choices_per_user: int = 999999, # 单个用户最大选择数
        ui_style: int = 1, # UI样式
        creator: discord.User | discord.Member | None = None, # 创建者
        intake_id: int | None = None # 提案创建时传入, 在投票频道发送提案支持人
    ):
        """
        为提案讨论帖创建投票面板，并尝试同步到投票频道
        采用两阶段提交模式
        """
        logger.info(f"接收到 'vote_session_created' 事件, 提案ID: {proposal_dto.id}")

        # 在讨论帖内创建核心投票面板
        try:
            vote_details = await self._create_in_thread_vote(
                proposal_dto, thread, duration_hours, anonymous, realtime,
                notify, options, max_choices_per_user, ui_style,
                creator=creator
            )
        except Exception as e:
            logger.error(
                f"为提案 {proposal_dto.id} 创建核心投票面板时发生错误: {e}", exc_info=True
            )
            return

        # 检查是否需要创建投票频道镜像，以及核心投票面板是否成功创建
        if not (create_in_voting_channel and vote_details and vote_details.context_message_id):
            return

        # 在投票频道创建镜像投票面板
        try:
            await self._create_voting_channel_mirror(
                proposal_dto,
                thread,
                vote_details,
                notify_creation_role,
            )

            # 如果是从草案转正时的投票创建，额外发送支持者名单
            if intake_id:
                await self._send_intake_founders_panel(
                    intake_id,
                    proposal_dto.title,
                    thread.jump_url,
                )

        except Exception as e:
            logger.error(
                f"为上下文消息 {vote_details.context_message_id} "
                f"创建镜像投票时发生非致命错误: {e}",
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
        max_choices_per_user: int = 999999,
        ui_style: int = 1,
        creator: discord.User | discord.Member | None = None
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
            max_choices_per_user: 单个用户的多选项数上限
            ui_style: 投票样式: 1-当前样式, 2-简洁样式

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
        if end_time and end_time < datetime.now(timezone.utc):
            end_time = None

        if end_time is None:
            end_time = TimeUtils.get_utc_end_time(duration_hours=duration_hours)

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
                max_choices_per_user=max_choices_per_user,
                ui_style=ui_style,
            )
            session_dto = await uow.vote_session.create_vote_session(qo)
            if not session_dto.id:
                raise ValueError("创建投票会话后未能获取ID")

            # 创建所有选项 (普通投票选项，option_type=0)
            await uow.vote_option.create_vote_options(
                session_dto.id,
                all_option_texts,
                option_type=0,
                creator_id=creator.id if creator else None,
                creator_name=creator.display_name if creator else None
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
                ui_style=ui_style,
                max_choices_per_user=max_choices_per_user,
            )

            view = VoteView(self.bot, vote_details=initial_vote_details)
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

            session = await uow.vote_session.get_vote_session_by_context_message_id(
                context_message_id
            )
            if not session:
                logger.warning(
                    f"未找到 context_message_id={context_message_id} "
                    "对应的投票会话，跳过创建镜像投票。"
                )
                return

            channel_view = VotingChannelView(self.bot, vote_details=vote_details)
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
                voting_channel.send(
                    content=content_to_send,
                    embeds=channel_embeds,
                    view=channel_view,
                ),
                priority=4,
            )

            if not session.id:
                logger.warning(
                    f"context_message_id={context_message_id} 对应会话缺少ID，跳过镜像消息关联。"
                )
                return

            session_id = session.id
            await uow.vote_session.update_voting_channel_message_id(
                session_id, voting_channel_message.id
            )
            await uow.commit()

        logger.debug(f"成功为会话 {session_id} 创建并关联了镜像投票")

    async def _send_intake_founders_panel(
        self,
        intake_id: int,
        proposal_title: str,
        thread_url: str,
    ):
        """查询草案阶段的支持者并发送名单面板到投票频道"""
        voting_channel_id_str = self.bot.config.get("channels", {}).get("voting_channel")
        if not voting_channel_id_str:
            return

        async with UnitOfWork(self.bot.db_handler) as uow:
            # 查找对应的草案支持票收集会话
            support_sessions = await uow.vote_session.get_vote_sessions_by_intake_id(intake_id)
            if not support_sessions:
                return
            support_session = support_sessions[0]

            # 检查会话ID是否存在
            if not support_session.id:
                logger.warning(f"intake_id={intake_id} 对应的支持会话缺少ID，跳过发送联署人名单")
                return

            # 查询该会话的所有投票人
            voters = await uow.user_vote.get_voter_by_session_id(support_session.id)
            voter_ids = [vote.user_id for vote in voters]

        if not voter_ids:
            return

        # 构建 Embed 并发送
        voting_channel = await DiscordUtils.fetch_channel(self.bot, int(voting_channel_id_str))
        if isinstance(voting_channel, discord.TextChannel):
            embed = VoteEmbedBuilder.create_intake_founders_embed(
                voter_ids,
                proposal_title,
                thread_url,
            )
            await self.bot.api_scheduler.submit(
                voting_channel.send(embed=embed),
                priority=4
            )


async def setup(bot: StellariaPactBot):
    await bot.add_cog(ModerationEventListener(bot))
