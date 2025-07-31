import logging

import discord
import regex as re
from discord.ext import commands

from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)




from StellariaPact.cogs.Voting.VotingService import VotingService


class MessageListener(commands.Cog):
    def __init__(self, bot: StellariaPactBot, voting_service: VotingService):
        self.bot = bot
        self.voting_service = voting_service
        # 移除纯表情的正则表达式
        self.emoji_pattern = re.compile(
            "^(<a?:\\w+:\\d+>|\\p{Emoji_Presentation}|\\p{Emoji_Modifier_Base}|\\p{Emoji_Component})+$"
        )

    def is_valid_message(self, message: discord.Message) -> bool:
        """
        检查消息是否为有效发言。
        有效发言：非纯表情，且长度超过5个字符。
        """
        content = message.content.strip()
        
        if not content or message.author.bot:
            logger.debug(
                f"消息被过滤: 作者是机器人({message.author.bot}) 或 内容为空('{content}')."
            )
            return False

        # 检查是否为纯表情
        if self.emoji_pattern.match(content):
            logger.debug(f"消息被过滤: 内容是纯表情 ('{content}').")
            return False

        # 检查长度
        is_long_enough = len(content) > 5
        if not is_long_enough:
            logger.debug(f"消息被过滤: 长度不足 ({len(content)} <= 5). 内容: '{content}'")
        else:
            logger.debug(f"消息验证通过: '{content}'")
            
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
        if not discussion_channel_id or message.channel.parent_id != int(
            discussion_channel_id
        ):
            return

        # 检查是否为有效发言
        if not self.is_valid_message(message):
            return

        try:
            async with self.bot.db_handler.get_session() as session:
                await self.voting_service.update_user_activity(
                    session, message.author.id, message.channel.id
                )
                logger.debug(
                    f"用户 {message.author.id} 在帖子 {message.channel.id} 的有效发言已记录"
                )
        except Exception as e:
            logger.error(
                f"更新用户 {message.author.id} 在帖子 {message.channel.id} 的活动时出错: {e}",
                exc_info=True,
            )
