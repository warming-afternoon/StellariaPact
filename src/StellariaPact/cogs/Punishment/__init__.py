import logging

from StellariaPact.share import StellariaPactBot

from .listeners.PunishmentListener import PunishmentListener
from .PunishmentCog import PunishmentCog

logger = logging.getLogger(__name__)


async def setup(bot: StellariaPactBot):
    """注册处罚控制器和发言拦截监听器。"""
    # 控制器处理交互，监听器恢复并维护禁言缓存。
    await bot.add_cog(PunishmentCog(bot))
    await bot.add_cog(PunishmentListener(bot))
    logger.info("成功加载 Punishment (处罚管理) 模块。")
