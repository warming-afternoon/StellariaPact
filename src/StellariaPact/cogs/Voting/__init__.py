from StellariaPact.cogs.Voting.Cog import Voting
from StellariaPact.cogs.Voting.listeners.MessageListener import MessageListener
from StellariaPact.cogs.Voting.listeners.ThreadListener import ThreadListener
from StellariaPact.cogs.Voting.tasks.VoteCloser import VoteCloser
from StellariaPact.cogs.Voting.VotingService import VotingService
from StellariaPact.share.StellariaPactBot import StellariaPactBot


async def setup(bot: StellariaPactBot):
    """
    设置并加载所有与投票相关的 Cogs。
    """
    # 创建一个共享的 VotingService 实例
    voting_service = VotingService()

    # 将所有相关的 Cogs 添加到 bot 中，并注入 service
    await bot.add_cog(Voting(bot, voting_service))
    await bot.add_cog(MessageListener(bot, voting_service))
    await bot.add_cog(ThreadListener(bot, voting_service))
    await bot.add_cog(VoteCloser(bot, voting_service))
