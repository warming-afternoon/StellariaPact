import logging
from typing import TYPE_CHECKING

from discord.ext import commands

from ..ModerationLogic import ModerationLogic

if TYPE_CHECKING:
    from ....share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


class NotificationEventListener(commands.Cog):
    """
    监听来自 Notification 模块的事件
    """

    def __init__(self, bot: "StellariaPactBot"):
        self.bot = bot
        self.logic = ModerationLogic(bot)

    @commands.Cog.listener("on_announcement_finished")
    async def on_announcement_finished(self, announcement):
        """
        监听由 Notification cog 分派的公示结束事件。
        """
        logger.info(
            f"接收到公示结束事件，帖子ID: {announcement.discussionThreadId}，分派到 logic 层处理。"
        )
        await self.logic.handle_announcement_finished(announcement)

async def setup(bot: "StellariaPactBot"):
    await bot.add_cog(NotificationEventListener(bot))