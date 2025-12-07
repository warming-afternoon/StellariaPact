import asyncio
import logging

from StellariaPact.share import StellariaPactBot

from .Cog import Moderation
from .listeners import ModerationListener, NotificationEventListener, VotingEventListener
from .ModerationLogic import ModerationLogic
from .tasks import ThreadReconciliation
from .views import ConfirmationView, ObjectionManageView

__all__ = [
    "Moderation",
    "ModerationLogic",
    "ModerationListener",
    "NotificationEventListener",
    "VotingEventListener",
    "ThreadReconciliation",
    "ConfirmationView",
    "ObjectionManageView",
]

logger = logging.getLogger(__name__)


async def setup(bot: StellariaPactBot):
    """
    设置并加载所有与议事管理相关的 Cogs。
    """
    # 为持久化视图注册
    bot.add_view(ConfirmationView(bot))
    bot.add_view(ObjectionManageView(bot))

    cogs_to_load = [
        Moderation(bot),
        ModerationListener(bot),
        VotingEventListener(bot),
        NotificationEventListener(bot),
        ThreadReconciliation(bot),
    ]
    await asyncio.gather(*[bot.add_cog(cog) for cog in cogs_to_load])
    logger.info(f"成功为 Moderation 模块加载了 {len(cogs_to_load)} 个 Cogs。")
