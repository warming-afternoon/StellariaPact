import os
import discord
import logging
import asyncio
import json
from pathlib import Path
from dotenv import load_dotenv

# --- .env 和 日志配置 ---
# 1. 首先加载环境变量
load_dotenv()

# 2. 强力配置根日志记录器
log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
log_level = getattr(logging, log_level_str, logging.INFO)
formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s')
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
root_logger = logging.getLogger()
root_logger.setLevel(log_level)
if root_logger.hasHandlers():
    root_logger.handlers.clear()
root_logger.addHandler(stream_handler)

logger = logging.getLogger('stellaria_pact')
# --- 日志配置结束 ---

# 3. 现在再导入我们自己的模块
from share.StellariaPactBot import StellariaPactBot
from share.ApiScheduler import APIScheduler
from share.DatabaseHandler import db_handler

# 这里是 Bot 的实例化和运行逻辑
def main():
    """主函数，设置并运行 Bot"""
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)

    proxy = config.get("proxy") or None
    bot = StellariaPactBot(command_prefix="!", intents=intents, proxy=proxy)
    
    bot.api_scheduler = APIScheduler()
    bot.db_handler = db_handler
    bot.config = config

    @bot.event
    async def setup_hook():
        bot.api_scheduler.start()
        await db_handler.init_db()
        
        logger.info("正在加载 Cogs...")
        cogs_path = Path("cogs")
        for cog_dir in cogs_path.iterdir():
            if cog_dir.is_dir():
                cog_main_file = cog_dir / "Cog.py"
                if cog_main_file.exists():
                    extension_path = f"cogs.{cog_dir.name}.Cog"
                    try:
                        await bot.load_extension(extension_path)
                        logger.info(f"成功加载 Cog: {extension_path}")
                    except Exception as e:
                        logger.exception(f"加载 Cog '{extension_path}' 失败: {e}")
        logger.info("Cogs 加载完成。")

        logger.info("正在同步命令...")
        await bot.tree.sync()
        logger.info("命令已同步。")

    @bot.event
    async def on_ready():
        logger.info(f'以 {bot.user} 的身份登录')
        logger.info('------ Bot 已准备就绪 ------')

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

if __name__ == "__main__":
    main()
