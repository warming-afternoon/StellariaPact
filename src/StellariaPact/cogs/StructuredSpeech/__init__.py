import logging

from StellariaPact.share import StellariaPactBot

from .StructuredSpeechCog import StructuredSpeechCog

logger = logging.getLogger(__name__)

__all__ = ["StructuredSpeechCog"]


async def setup(bot: StellariaPactBot) -> None:
    """注册提案结构化发言控制器。"""
    await bot.add_cog(StructuredSpeechCog(bot))
    logger.info("已加载提案结构化发言模块。")
