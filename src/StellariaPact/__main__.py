import asyncio
import json
import logging
import os
from pathlib import Path

import discord
from dotenv import load_dotenv

from StellariaPact.share.ApiScheduler import APIScheduler
from StellariaPact.share.DatabaseHandler import db_handler
from StellariaPact.share.HttpClient import HttpClient
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.TimeUtils import TimeUtils

# --- .env 和 日志配置 ---
load_dotenv()

# 配置根日志记录器
log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_str, logging.INFO)
formatter = logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s")
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
root_logger = logging.getLogger()
root_logger.setLevel(log_level)
if root_logger.hasHandlers():
    root_logger.handlers.clear()
root_logger.addHandler(stream_handler)

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
    bot.db_handler = db_handler
    bot.config = config
    bot.time_utils = TimeUtils()

    @bot.event
    async def setup_hook():
        bot.api_scheduler.start()

        # --- 并行化启动任务 ---
        logger.info("正在加载 Cogs 和初始化数据库...")

        # 收集所有需要并行执行的异步任务
        tasks = []

        # 1. 添加数据库初始化任务
        tasks.append(db_handler.init_db())

        # 2. 添加所有 Cogs 的加载任务
        cogs_path = Path(__file__).parent / "cogs"
        for cog_dir in cogs_path.iterdir():
            if cog_dir.is_dir():
                cog_main_file = cog_dir / "Cog.py"
                if cog_main_file.exists():
                    extension_path = f"StellariaPact.cogs.{cog_dir.name}.Cog"
                    tasks.append(bot.load_extension(extension_path))

        # 使用 asyncio.gather 并行执行所有任务
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 检查任务执行结果
        cog_names = [f"Cog {cog.name}" for cog in cogs_path.glob("*/Cog.py")]
        for result, task_name in zip(results, ["DB Init"] + cog_names):
            if isinstance(result, Exception):
                logger.exception(f"初始化任务 '{task_name}' 失败: {result}")
            else:
                logger.info(f"初始化任务 '{task_name}' 成功完成。")

        logger.info("Cogs 和数据库初始化完成。")

        logger.info("正在同步命令...")
        await bot.tree.sync()
        logger.info("命令已同步。")

    @bot.event
    async def on_ready():
        logger.info(f"以 {bot.user} 的身份登录")
        
        # --- 重新注册持久化视图 ---
        from StellariaPact.cogs.Voting.views.VoteView import VoteView
        from StellariaPact.cogs.Voting.VotingService import VotingService
        
        logger.info("正在重新注册持久化视图...")
        try:
            voting_service = VotingService()
            bot.add_view(VoteView(bot, voting_service))
            logger.info("VoteView 已成功重新注册。")
        except Exception as e:
            logger.error(f"重新注册 VoteView 时出错: {e}", exc_info=True)
        
        logger.info("------ Bot 已准备就绪 ------")

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
