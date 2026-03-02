import logging

from StellariaPact.share import StellariaPactBot

from .Cog import PunishmentCog
from .listeners.PunishmentListener import PunishmentListener

logger = logging.getLogger(__name__)

async def setup(bot: StellariaPactBot):
    await bot.add_cog(PunishmentCog(bot))
    await bot.add_cog(PunishmentListener(bot))
    logger.info("成功加载 Punishment (处罚管理) 模块。")
