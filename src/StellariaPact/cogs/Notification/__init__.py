import asyncio
import logging

from StellariaPact.cogs.Notification.BackgroundTasks import BackgroundTasks
from StellariaPact.cogs.Notification.Cog import Notification
from StellariaPact.cogs.Notification.listeners.AnnounceMessageListener import (
    AnnounceMessageListener,
)
from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


async def setup(bot: StellariaPactBot):
    """
    设置并加载所有与通知相关的 Cogs
    """
    cogs_to_load = [
        Notification(bot),
        BackgroundTasks(bot),
        AnnounceMessageListener(bot),
    ]

    await asyncio.gather(*[bot.add_cog(cog) for cog in cogs_to_load])
    logger.info(f"成功为 Notification 模块加载了 {len(cogs_to_load)} 个 Cogs")
