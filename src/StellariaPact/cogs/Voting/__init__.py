import asyncio
import logging

from StellariaPact.cogs.Voting.views import ObjectionSupportView
from StellariaPact.share.StellariaPactBot import StellariaPactBot

from .Cog import Voting
from .EligibilityService import EligibilityService
from .listeners.DiscussionMessageListener import DiscussionMessageListener
from .listeners.InnerEventListener import InnerEventListener
from .listeners.MessageEventApiCog import MessageEventApiCog
from .listeners.ModerationEventListener import ModerationEventListener
from .tasks.VoteCloser import VoteCloser
from .views.VoteView import VoteView
from .views.VotingChannelView import VotingChannelView
from .VotingLogic import VotingLogic

__all__ = [
    "Voting",
    "EligibilityService",
    "VotingLogic",
    "ModerationEventListener",
    "InnerEventListener",
    "DiscussionMessageListener",
    "MessageEventApiCog",
    "VoteCloser",
    "VoteView",
    "VotingChannelView",
]

logger = logging.getLogger(__name__)


def create_message_listener(
    bot: StellariaPactBot,
    voting_cog: Voting,
) -> DiscussionMessageListener | MessageEventApiCog:
    """根据配置创建唯一的资格消息监听器。"""
    # 远端模式只启动带鉴权的 HTTP 消息事件接收端。
    if bot.remote_message_events.enabled:
        return MessageEventApiCog(
            bot,
            voting_cog,
            bot.remote_message_events,
        )

    # 本地模式直接读取 Discord 消息正文并统计资格。
    return DiscussionMessageListener(bot, voting_cog)


async def setup(bot: StellariaPactBot) -> None:
    """设置并加载所有与投票相关的 Cog。"""
    # 注册持久化视图。
    bot.add_view(VoteView(bot))
    bot.add_view(VotingChannelView(bot))
    bot.add_view(ObjectionSupportView(bot))
    # 实例化核心 Cog。
    voting_cog = Voting(bot)

    # 资格消息只选择一个来源，避免本地监听和远端事件重复计数。
    message_listener = create_message_listener(bot, voting_cog)

    # 实例化依赖于其他 Cog 的组件并注入依赖。
    cogs_to_load = [
        voting_cog,
        VoteCloser(bot),
        ModerationEventListener(bot),
        message_listener,
        InnerEventListener(bot),
    ]

    # 并发注册彼此独立的 Cog。
    await asyncio.gather(*[bot.add_cog(cog) for cog in cogs_to_load])
    logger.info(f"成功为 Voting 模块加载了 {len(cogs_to_load)} 个 Cogs。")
