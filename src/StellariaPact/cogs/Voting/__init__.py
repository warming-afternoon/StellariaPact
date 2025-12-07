import asyncio
import logging

from StellariaPact.share.StellariaPactBot import StellariaPactBot

from .Cog import Voting
from .EligibilityService import EligibilityService
from .listeners.ModerationEventListener import ModerationEventListener
from .listeners.ViewEventListener import ViewEventListener
from .listeners.VotingMessageListener import VotingMessageListener
from .tasks.VoteCloser import VoteCloser
from .views import ObjectionCreationVoteView
from .views.ObjectionFormalVoteView import ObjectionFormalVoteView
from .views.VoteView import VoteView
from .views.VotingChannelView import VotingChannelView
from .VotingLogic import VotingLogic

__all__ = [
    "Voting",
    "EligibilityService",
    "VotingLogic",
    "ModerationEventListener",
    "ViewEventListener",
    "VotingMessageListener",
    "VoteCloser",
    "ObjectionFormalVoteView",
    "VoteView",
    "VotingChannelView",
]

logger = logging.getLogger(__name__)


async def setup(bot: StellariaPactBot):
    """
    设置并加载所有与投票相关的 Cogs。
    """
    # 注册持久化视图
    bot.add_view(VoteView(bot))
    bot.add_view(ObjectionFormalVoteView(bot))
    bot.add_view(VotingChannelView(bot))
    bot.add_view(ObjectionCreationVoteView(bot))

    # 实例化核心 Cog
    voting_cog = Voting(bot)

    # 实例化依赖于其他 Cogs 的组件，并注入依赖
    cogs_to_load = [
        voting_cog,
        VoteCloser(bot),
        ModerationEventListener(bot),
        VotingMessageListener(bot, voting_cog),
        ViewEventListener(bot),
    ]

    await asyncio.gather(*[bot.add_cog(cog) for cog in cogs_to_load])
    logger.info(f"成功为 Voting 模块加载了 {len(cogs_to_load)} 个 Cogs。")
