import asyncio
import json
import logging
import os
from pathlib import Path

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

logger = logging.getLogger("stellaria_pact")
# --- 日志配置结束 ---


#  Bot 的实例化和运行逻辑
def main():
    """主函数，设置并运行 Bot"""
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True

    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    proxy = config.get("proxy") or None
    bot = StellariaPactBot(command_prefix="!", intents=intents, proxy=proxy)

    bot.api_scheduler = APIScheduler()
    # db_handler 将在 setup_hook 中被初始化和分配
    bot.db_handler = None
    bot.config = config
    bot.time_utils = TimeUtils()

    @bot.event
    async def setup_hook():
        # logger.info("正在显式加载所有数据模型...")
        import StellariaPact.models  # noqa: F401

        # logger.info("数据模型加载完成。")
        bot.api_scheduler.start()

        # 初始化 DatabaseHandler 并将其分配给 Bot
        logger.info("正在初始化 DatabaseHandler...")
        initialize_db_handler()
        bot.db_handler = get_db_handler()
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

        logger.info("正在加载所有 Cogs...")
        cogs_path = Path(__file__).parent / "cogs"
        cog_load_tasks = []
        for cog_dir in cogs_path.iterdir():
            if cog_dir.is_dir() and (cog_dir / "__init__.py").exists():
                extension_path = f"StellariaPact.cogs.{cog_dir.name}"
                cog_load_tasks.append(bot.load_extension(extension_path))

        if cog_load_tasks:
            results = await asyncio.gather(*cog_load_tasks, return_exceptions=True)
            # 检查 Cogs 加载结果
            cog_names = [
                cog.name
                for cog in cogs_path.iterdir()
                if cog.is_dir() and (cog / "__init__.py").exists()
            ]
            for result, name in zip(results, cog_names):
                if isinstance(result, Exception):
                    logger.exception(f"加载 Cog '{name}' 失败: {result}")
                else:
                    logger.info(f"成功加载 Cog: {name}")
        logger.info("所有 Cogs 加载完成。")

        logger.info("正在同步命令...")
        await bot.api_scheduler.submit(bot.tree.sync(), priority=5)
        logger.info("命令已同步。")

    @bot.event
    async def on_ready():
        logger.info(f"以 {bot.user} 的身份登录")

        logger.info("------ Bot 已准备就绪 ------")

    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        """
        全局应用命令错误处理器。
        """
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

    try:
        asyncio.run(bot.start(token, reconnect=True))
    except KeyboardInterrupt:
        logger.info("检测到手动中断，正在关闭 Bot...")
    except Exception:
        logger.exception("Bot 运行时发生未捕获的异常")
    finally:
        # 确保 aiohttp session 在程序退出时被关闭
        asyncio.run(HttpClient.close())


if __name__ == "__main__":
    main()
