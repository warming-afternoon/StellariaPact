import logging
from typing import TYPE_CHECKING

from discord.ext import commands

from StellariaPact.cogs.Moderation.ModerationLogic import ModerationLogic
from StellariaPact.cogs.Moderation.thread_manager import ProposalThreadManager

if TYPE_CHECKING:
    from StellariaPact.share import StellariaPactBot

logger = logging.getLogger(__name__)


class VotingEventListener(commands.Cog):
    """
    监听来自 Voting 模块的事件
    """

    def __init__(self, bot: "StellariaPactBot"):
        self.bot = bot
        self.logic = ModerationLogic(bot)
        self.thread_manager = ProposalThreadManager(bot.config)
