import logging

import discord
import regex as re
from discord.ext import commands

from StellariaPact.cogs.Voting.EligibilityService import EligibilityService
from StellariaPact.cogs.Voting.qo.GetVoteDetailsQo import GetVoteDetailsQo
from StellariaPact.cogs.Voting.qo.UpdateUserActivityQo import UpdateUserActivityQo
from StellariaPact.cogs.Voting.views.VoteEmbedBuilder import VoteEmbedBuilder
from StellariaPact.cogs.Voting.VotingService import VotingService
from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


class MessageListener(commands.Cog):
    def __init__(self, bot: StellariaPactBot, voting_service: VotingService):
        self.bot = bot
        self.voting_service = voting_service
        # 移除纯表情的正则表达式
        self.emoji_pattern = re.compile(
            "^(<a?:\\w+:\\d+>|\\p{Emoji_Presentation}|\\p{Emoji_Modifier_Base}|\\p{Emoji_Component}|\\p{So}|\\p{Cn})+$"
        )

    def is_valid_message(self, message: discord.Message) -> bool:
        """
        检查消息是否为有效发言。
        有效发言：非纯表情，且长度超过5个字符。
        """
        content = message.content.strip()

        if not content or message.author.bot:
            logger.debug(f"消息被过滤: 作者是机器人({message.author.bot}) 或 内容为空")
            return False

        # 移除所有空白字符，然后检查是否为纯表情
        content_without_whitespace = re.sub(r"\s", "", content)
        if self.emoji_pattern.match(content_without_whitespace):
            # logger.debug(f"消息被过滤: 内容是纯表情 ('{content}')")
            return False

        # 检查长度
        is_long_enough = len(content_without_whitespace) > 5
        # if not is_long_enough:
        #     logger.debug(f"消息被过滤: 长度不足 ({len(content)} <= 5)'")
        # else:
        #     pass
        #     # logger.debug(f"消息验证通过: '{content}'")

        return is_long_enough

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        监听所有消息，以更新用户在帖子中的活动。
        """
        # 仅处理我们关心的讨论区帖子中的消息
        if not isinstance(message.channel, discord.Thread):
            return

        discussion_channel_id = self.bot.config.get("channels", {}).get("discussion")
        if not discussion_channel_id or message.channel.parent_id != int(discussion_channel_id):
            return

        # 检查是否为有效发言
        if not self.is_valid_message(message):
            return

        try:
            async with self.bot.db_handler.get_session() as session:
                await self.voting_service.update_user_activity(
                    session,
                    UpdateUserActivityQo(
                        user_id=message.author.id, thread_id=message.channel.id, change=1
                    ),
                )
        except Exception as e:
            logger.error(
                f"更新用户 {message.author.id} 在帖子 {message.channel.id} 的活动时出错: {e}",
                exc_info=True,
            )

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        """
        监听消息删除事件，以更新用户在帖子中的活动。
        """
        # 仅处理我们关心的讨论区帖子中的消息
        if not isinstance(message.channel, discord.Thread):
            return

        discussion_channel_id = self.bot.config.get("channels", {}).get("discussion")
        if not discussion_channel_id or message.channel.parent_id != int(discussion_channel_id):
            return

        # 检查是否为有效发言
        if not self.is_valid_message(message):
            return

        try:
            async with self.bot.db_handler.get_session() as session:
                # 更新用户活动计数
                user_activity = await self.voting_service.update_user_activity(
                    session,
                    UpdateUserActivityQo(
                        user_id=message.author.id, thread_id=message.channel.id, change=-1
                    ),
                )

                # 检查用户是否还有投票资格
                if EligibilityService.is_eligible(user_activity):
                    return

                # 如果没有资格，则尝试删除他们的投票
                vote_deleted = await self.voting_service.delete_user_vote(
                    session, user_id=message.author.id, thread_id=message.channel.id
                )

                # 如果确实删除了投票（意味着他们之前投过票），则更新公共面板
                if vote_deleted:
                    vote_session = await self.voting_service.get_vote_session_by_thread_id(
                        session, message.channel.id
                    )
                    if not vote_session or not vote_session.realtimeFlag:
                        return

                    # 获取最新的投票详情
                    vote_details = await self.voting_service.get_vote_details(
                        session, GetVoteDetailsQo(thread_id=message.channel.id)
                    )

                    # 获取公共投票消息并更新它
                    try:
                        thread = self.bot.get_channel(
                            message.channel.id
                        ) or await self.bot.fetch_channel(message.channel.id)
                        if not isinstance(thread, discord.Thread):
                            return

                        public_message = await thread.fetch_message(vote_session.contextMessageId)
                        new_embed = VoteEmbedBuilder.update_vote_counts_embed(
                            public_message.embeds[0], vote_details
                        )
                        await self.bot.api_scheduler.submit(
                            public_message.edit(embed=new_embed), priority=2
                        )
                        logger.info(
                            f"用户 {message.author.id} 因资格失效，"
                            f"其在帖子 {message.channel.id} 的投票已被撤销。"
                        )
                    except discord.NotFound:
                        logger.warning(
                            f"在帖子 {message.channel.id} 中未找到原始投票消息，无法更新面板。"
                        )

        except Exception as e:
            logger.error(
                "处理用户 %s 在帖子 %s 的消息删除事件时出错: %s",
                message.author.id,
                message.channel.id,
                e,
                exc_info=True,
            )
