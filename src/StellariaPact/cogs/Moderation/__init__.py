import asyncio
import logging

from StellariaPact.cogs.Moderation.Cog import Moderation
from StellariaPact.cogs.Moderation.listeners.ModerationListener import ModerationListener
from StellariaPact.cogs.Moderation.views.ConfirmationView import ConfirmationView
from StellariaPact.cogs.Moderation.views.ObjectionManageView import ObjectionManageView
from StellariaPact.cogs.Voting.views.ObjectionCreationVoteView import (
    ObjectionCreationVoteView,
)
from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


async def setup(bot: StellariaPactBot):
    """
    设置并加载所有与议事管理相关的 Cogs。
    """
    # 为持久化视图注册
    bot.add_view(ConfirmationView(bot))
    bot.add_view(ObjectionManageView(bot))
    bot.add_view(ObjectionCreationVoteView(bot))

    cogs_to_load = [Moderation(bot), ModerationListener(bot)]
    await asyncio.gather(*[bot.add_cog(cog) for cog in cogs_to_load])
    logger.info(f"成功为 Moderation 模块加载了 {len(cogs_to_load)} 个 Cogs。")
