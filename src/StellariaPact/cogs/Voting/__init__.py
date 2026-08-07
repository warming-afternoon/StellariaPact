import asyncio
import logging

from StellariaPact.cogs.Voting.views import ObjectionSupportView
from StellariaPact.share.StellariaPactBot import StellariaPactBot

from .Cog import Voting
from .EligibilityService import EligibilityService
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
    "MessageEventApiCog",
    "VoteCloser",
    "VoteView",
    "VotingChannelView",
]

logger = logging.getLogger(__name__)


async def setup(bot: StellariaPactBot) -> None:
    """设置并加载所有与投票相关的 Cog。"""
    # 注册持久化视图。
    bot.add_view(VoteView(bot))
    bot.add_view(VotingChannelView(bot))
    bot.add_view(ObjectionSupportView(bot))
    # 实例化核心 Cog。
    voting_cog = Voting(bot)

    # 实例化依赖于其他 Cog 的组件并注入依赖。
    cogs_to_load = [
        voting_cog,
        VoteCloser(bot),
        ModerationEventListener(bot),
        MessageEventApiCog(bot, voting_cog),
        InnerEventListener(bot),
    ]

    # 并发注册彼此独立的 Cog。
    await asyncio.gather(*[bot.add_cog(cog) for cog in cogs_to_load])
    logger.info(f"成功为 Voting 模块加载了 {len(cogs_to_load)} 个 Cogs。")
