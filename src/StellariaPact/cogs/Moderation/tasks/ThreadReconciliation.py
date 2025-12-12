import asyncio
import logging
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks

from StellariaPact.cogs.Moderation import ModerationLogic
from StellariaPact.share import DiscordUtils, StellariaPactBot

logger = logging.getLogger(__name__)


class ThreadReconciliation(commands.Cog):
    """
    后台任务的 Cog，用于查找并处理可能被 on_thread_create 事件遗漏的提案帖子。
    """

    def __init__(self, bot: "StellariaPactBot"):
        self.bot = bot
        self.logic = ModerationLogic(bot)
        self.reconcile_missing_threads.start()

    def cog_unload(self):
        self.reconcile_missing_threads.cancel()

    @tasks.loop(minutes=2)
    async def reconcile_missing_threads(self):
        """
        定期从讨论区论坛获取最近的帖子，并处理任何尚未在数据库中记录的帖子。
        """
        logger.debug("正在运行提案帖子审计任务...")
        try:
            discussion_channel_id_str = self.bot.config.get("channels", {}).get("discussion")
            if not discussion_channel_id_str:
                logger.warning("提案讨论频道未配置，跳过审计任务")
                return

            channel = await DiscordUtils.fetch_channel(self.bot, int(discussion_channel_id_str))
            if not isinstance(channel, discord.ForumChannel):
                logger.error("讨论频道不是一个有效的论坛频道，跳过审计")
                return

            three_days_ago = datetime.now(timezone.utc) - timedelta(days=3)

            # 合并活跃的和最近归档的帖子进行检查
            threads_to_check = []
            threads_to_check.extend(channel.threads)

            # 获取最近归档的帖子
            try:
                async for thread in channel.archived_threads(limit=100):
                    if thread.created_at and thread.created_at > three_days_ago:
                        threads_to_check.append(thread)

            except discord.Forbidden:
                logger.warning(f"缺少在频道 {channel.name} 中读取已归档帖子的权限")
            except Exception as e:
                logger.error(f"获取已归档帖子以进行审计时出错: {e}", exc_info=True)

            unique_threads = {t.id: t for t in threads_to_check}.values()

            for thread in unique_threads:
                if not thread.created_at or thread.created_at <= three_days_ago:
                    continue

                await asyncio.sleep(1)
                await self.logic.process_new_discussion_thread(thread)

        except Exception as e:
            logger.error(f"提案帖子审计任务中发生意外错误: {e}", exc_info=True)

    @reconcile_missing_threads.before_loop
    async def before_reconciliation_loop(self):
        await self.bot.wait_until_ready()
        logger.info("提案帖子审计任务已准备就绪。")


async def setup(bot: "StellariaPactBot"):
    await bot.add_cog(ThreadReconciliation(bot))
