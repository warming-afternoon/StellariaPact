import asyncio
import logging
from typing import cast

import discord
import regex as re
from discord.ext import commands

from StellariaPact.cogs.Voting.Cog import Voting
from StellariaPact.cogs.Voting.qo.UpdateUserActivityQo import \
    UpdateUserActivityQo
from StellariaPact.cogs.Voting.views.VoteEmbedBuilder import VoteEmbedBuilder
from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


class VotingMessageListener(commands.Cog):
    def __init__(self, bot: StellariaPactBot, voting_cog: Voting):
        self.bot = bot
        self.voting_cog = voting_cog
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
            return False

        # 检查长度
        is_long_enough = len(content_without_whitespace) > 5

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
            qo = UpdateUserActivityQo(
                user_id=message.author.id,
                thread_id=message.channel.id,
                change=1,
            )
            await self.voting_cog.logic.handle_message_creation(qo)
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
            # 调用核心逻辑
            qo = UpdateUserActivityQo(
                user_id=message.author.id,
                thread_id=message.channel.id,
                change=-1,
            )
            details_to_update = await self.voting_cog.logic.handle_message_deletion(qo)

            # 如果没有返回详情，说明无需更新 UI
            if not details_to_update:
                return

            # 并行更新所有需要更新的投票面板
            thread = message.channel
            update_tasks = []
            for details in details_to_update:
                if details.context_message_id:
                    try:
                        msg = await thread.fetch_message(details.context_message_id)
                        new_embed = VoteEmbedBuilder.create_vote_panel_embed(
                            topic=thread.name,
                            anonymous_flag=details.is_anonymous,
                            realtime_flag=details.realtime_flag,
                            end_time=details.end_time,
                            vote_details=details,
                        )
                        update_tasks.append(msg.edit(embed=new_embed))
                    except discord.NotFound:
                        logger.warning(
                            f"在帖子 {thread.id} 中未找到投票消息 {details.context_message_id}，无法更新面板。"
                        )
                    except IndexError:
                        logger.warning(
                            f"投票消息 {details.context_message_id} 缺少 embed，无法更新。"
                        )

            if update_tasks:
                await asyncio.gather(
                    *(self.bot.api_scheduler.submit(task, priority=2) for task in update_tasks)
                )
                logger.info(
                    f"用户 {message.author.id} 因资格失效，"
                    f"其在帖子 {thread.id} 的投票已被撤销并更新了 {len(update_tasks)} 个面板。"
                )

        except Exception as e:
            logger.error(
                "处理用户 %s 在帖子 %s 的消息删除事件时出错: %s",
                message.author.id,
                message.channel.id,
                e,
                exc_info=True,
            )
