import asyncio
import logging

from StellariaPact.cogs.Voting.Cog import Voting
from StellariaPact.cogs.Voting.listeners.ModerationEventListener import \
    ModerationEventListener
from StellariaPact.cogs.Voting.listeners.VotingMessageListener import \
    VotingMessageListener
from StellariaPact.cogs.Voting.tasks.VoteCloser import VoteCloser
from StellariaPact.cogs.Voting.views.ObjectionFormalVoteView import \
    ObjectionFormalVoteView
from StellariaPact.cogs.Voting.views.VoteView import VoteView
from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


async def setup(bot: StellariaPactBot):
    """
    设置并加载所有与投票相关的 Cogs。
    """
    # 注册持久化视图
    bot.add_view(VoteView(bot))
    bot.add_view(ObjectionFormalVoteView(bot))

    # 注意：Eligibility cog 未在此处定义或导入，假设它在别处处理或暂时移除
    cogs_to_load = [
        Voting(bot),
        VotingMessageListener(bot),
        VoteCloser(bot),
        ModerationEventListener(bot),
    ]

    await asyncio.gather(*[bot.add_cog(cog) for cog in cogs_to_load])
    logger.info(f"成功为 Voting 模块加载了 {len(cogs_to_load)} 个 Cogs。")
