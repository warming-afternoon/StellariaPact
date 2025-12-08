import asyncio
import json
import logging
import os
import sys

import aiorun
import discord
from discord import app_commands
from dotenv import load_dotenv

from StellariaPact.share.ApiScheduler import APIScheduler
from StellariaPact.share.auth.MissingRole import MissingRole
from StellariaPact.share.DatabaseHandler import get_db_handler, initialize_db_handler
from StellariaPact.share.HttpClient import HttpClient
from StellariaPact.share.LoggingConfigurator import LoggingConfigurator
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.TimeUtils import TimeUtils

# --- .env 和 日志配置 ---
load_dotenv()
log_level = os.getenv("LOG_LEVEL", "INFO")
configurator = LoggingConfigurator(rootLogLevel=log_level)
configurator.configure()

logger = logging.getLogger("StellariaPact")
# --- 日志配置结束 ---


if sys.platform != "win32":
    try:
        import uvloop

        uvloop.install()
        logger.info("已成功启用 uvloop 作为 asyncio 事件循环")
    except ImportError:
        logger.warning("尝试启用 uvloop 失败，将使用默认事件循环")


bot = None
db_handler = None


async def shutdown(loop):
    """专门用于清理资源的关闭回调函数"""
    global bot, db_handler
    logger.info("收到关闭信号，正在关闭 Bot 资源...")
    if bot:
        await bot.close()

    await HttpClient.close()

    if db_handler:
        await db_handler.close()

    if bot and bot.api_scheduler:
        await bot.api_scheduler.stop()

    logger.info("所有资源已清理，程序退出。")


async def main_async():
    """主函数，设置并运行 Bot"""
    global bot, db_handler
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True

    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    proxy = config.get("proxy") or None
    bot = StellariaPactBot(command_prefix="!", intents=intents, proxy=proxy)

    bot.api_scheduler = APIScheduler()
    bot.db_handler = None
    bot.config = config
    bot.time_utils = TimeUtils()

    @bot.event
    async def setup_hook():
        global db_handler
        assert bot is not None
        import StellariaPact.models  # noqa: F401

        bot.api_scheduler.start()

        initialize_db_handler()
        db_handler = get_db_handler()  # 将实例赋给全局变量
        bot.db_handler = db_handler
        logger.info("DatabaseHandler 初始化并分配给 Bot。")

        # 使用 Bot 上的句柄初始化数据库表
        logger.info("正在检查数据库表...")
        try:
            await bot.db_handler.init_db()
            logger.info("数据库表处理成功。")
        except Exception as e:
            logger.exception(f"数据库表处理失败: {e}")
            # 如果数据库初始化失败，可能不应该继续，这里可以选择直接返回或抛出异常
            return

        logger.info("开始加载所有 Cogs 模块...")
        from StellariaPact.cogs import Moderation, Notification, Voting

        # 依次调用每个模块的 setup 函数
        module_setups = [
            Moderation.setup(bot),
            Notification.setup(bot),
            Voting.setup(bot),
        ]
        try:
            await asyncio.gather(*module_setups)
            logger.info("所有 Cogs 模块加载完成。")
        except Exception as e:
            logger.exception(f"加载 Cogs 模块时发生错误: {e}")

        logger.info("正在同步命令...")
        await bot.api_scheduler.submit(bot.tree.sync(), priority=5)
        logger.info("命令已同步。")

    @bot.event
    async def on_ready():
        assert bot is not None
        logger.info(f"以 {bot.user} 的身份登录")

        logger.info("------ Bot 已准备就绪 ------")

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        """
        全局应用命令错误处理器。
        """
        assert bot is not None
        original_error = getattr(error, "original", error)
        if isinstance(original_error, MissingRole):
            if not interaction.response.is_done():
                await bot.api_scheduler.submit(
                    interaction.response.send_message(str(original_error), ephemeral=True),
                    priority=1,
                )
        else:
            logger.error(f"在应用命令中发生未处理的错误: {error}", exc_info=True)
            if not interaction.response.is_done():
                await bot.api_scheduler.submit(
                    interaction.response.send_message(
                        "发生了一个未知错误，请联系技术员", ephemeral=True
                    ),
                    priority=1,
                )

    token = os.getenv("DISCORD_TOKEN")
    if not token or token == "YOUR_BOT_TOKEN_HERE":
        logger.error("错误: 未找到或未配置 DISCORD_TOKEN。")
        return

    await bot.start(token)


def main():
    """主入口函数"""
    aiorun.run(main_async(), shutdown_callback=shutdown, stop_on_unhandled_errors=True)


if __name__ == "__main__":
    main()
