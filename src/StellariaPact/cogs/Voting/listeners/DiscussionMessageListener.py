import asyncio
import logging

import discord
import regex as re
from discord.ext import commands

from StellariaPact.cogs.Voting.Cog import Voting
from StellariaPact.cogs.Voting.views import VoteEmbedBuilder
from StellariaPact.dto.vote_session import VoteDetailDto
from StellariaPact.qo.user_activity import UpdateUserActivityQo
from StellariaPact.share import StellariaPactBot

logger = logging.getLogger(__name__)


class DiscussionMessageListener(commands.Cog):
    """监听讨论论坛中的有效发言并维护用户投票资格。"""

    def __init__(self, bot: StellariaPactBot, voting_cog: Voting):
        """初始化本地讨论消息监听器。"""
        # 保存 Bot 与资格业务逻辑依赖。
        self.bot = bot
        self.voting_cog = voting_cog

        # 编译与远端转发器一致的纯表情识别规则。
        self.emoji_pattern = re.compile(
            r"^(<a?:\w+:\d+>|\p{Emoji_Presentation}|\p{Emoji_Modifier_Base}|"
            r"\p{Emoji_Component}|\p{So}|\p{Cn})+$"
        )

    def is_valid_message(self, message: discord.Message) -> bool:
        """判断消息是否满足投票资格的有效发言规则。"""
        # 忽略空消息和机器人消息。
        content = message.content.strip()
        if not content or message.author.bot:
            return False

        # 移除空白后排除纯表情内容。
        content_without_whitespace = re.sub(r"\s", "", content)
        if self.emoji_pattern.match(content_without_whitespace):
            return False

        # 有效发言必须超过四个非空白字符。
        return len(content_without_whitespace) > 4

    def _is_target_message(self, message: discord.Message) -> bool:
        """判断消息是否来自配置的讨论论坛帖子。"""
        # 本地模式只处理目标父论坛下的 Discord 帖子。
        if not isinstance(message.channel, discord.Thread):
            return False

        discussion_channel_id = self.bot.config.get("channels", {}).get("discussion")
        try:
            return message.channel.parent_id == int(discussion_channel_id)
        except (TypeError, ValueError):
            # 本地论坛配置无效时拒绝处理全部消息。
            return False

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """监听新消息并增加有效发言计数。"""
        # 非目标论坛或无效发言不会进入资格业务逻辑。
        if not self._is_target_message(message) or not self.is_valid_message(message):
            return

        try:
            # 创建事件交由服务层更新用户活动计数。
            thread = message.channel
            assert isinstance(thread, discord.Thread)
            qo = UpdateUserActivityQo(
                user_id=message.author.id,
                thread_id=thread.id,
                change=1,
            )
            await self.voting_cog.logic.handle_message_creation(qo)
        except Exception:
            # 单条消息失败只记录异常，不中断 Discord 事件循环。
            logger.exception(
                "更新用户 %s 在帖子 %s 的活动时出错。",
                message.author.id,
                message.channel.id,
            )

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        """监听缓存内消息删除并减少有效发言计数。"""
        # 仅处理目标论坛内仍能从缓存校验正文的有效消息。
        if not self._is_target_message(message) or not self.is_valid_message(message):
            return

        try:
            # 删除事件交由服务层处理计数、资格失效与跨表撤票。
            thread = message.channel
            assert isinstance(thread, discord.Thread)
            qo = UpdateUserActivityQo(
                user_id=message.author.id,
                thread_id=thread.id,
                change=-1,
            )
            details_to_update = await self.voting_cog.logic.handle_message_deletion(qo)

            # 没有撤票详情时无需刷新 Discord 面板。
            if not details_to_update:
                return

            # 并发刷新彼此独立的投票面板，避免串行外部请求形成 N+1 延迟。
            await asyncio.gather(
                *(self._refresh_vote_panel(thread, details) for details in details_to_update)
            )
        except Exception:
            # 保留完整堆栈便于排查计数或面板刷新失败。
            logger.exception(
                "处理用户 %s 在帖子 %s 的消息删除事件时出错。",
                message.author.id,
                message.channel.id,
            )

    async def _refresh_vote_panel(
        self,
        thread: discord.Thread,
        details: VoteDetailDto,
    ) -> None:
        """刷新单个受资格变化影响的投票面板。"""
        # 没有关联消息的投票详情无需访问 Discord。
        if not details.context_message_id:
            return

        try:
            # 每个面板只获取一次对应消息并构造最新 Embed。
            message = await thread.fetch_message(details.context_message_id)
            embeds = VoteEmbedBuilder.create_vote_panel_embed_v2(
                topic=thread.name,
                vote_details=details,
            )

            # 通过统一调度器提交编辑请求以遵守 Discord 限流策略。
            await self.bot.api_scheduler.submit(message.edit(embeds=embeds), priority=2)
        except (discord.NotFound, discord.Forbidden):
            logger.warning(
                "在帖子 %s 中无法获取投票消息 %s。",
                thread.id,
                details.context_message_id,
            )
        except IndexError:
            logger.warning("投票消息 %s 缺少可用 Embed。", details.context_message_id)
