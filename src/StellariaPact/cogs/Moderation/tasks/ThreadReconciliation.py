import asyncio
import logging
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks

from ....share.DiscordUtils import DiscordUtils
from ....share.StellariaPactBot import StellariaPactBot
from ....share.UnitOfWork import UnitOfWork
from ..ModerationLogic import ModerationLogic

logger = logging.getLogger(__name__)


class ThreadReconciliation(commands.Cog):
    """
    一个包含后台任务的 Cog，用于查找并处理可能被 on_thread_create 事件遗漏的提案帖子。
    """

    def __init__(self, bot: "StellariaPactBot"):
        self.bot = bot
        self.logic = ModerationLogic(bot)
        self.reconcile_missing_threads.start()

    def cog_unload(self):
        self.reconcile_missing_threads.cancel()

    @tasks.loop(minutes=1)
    async def reconcile_missing_threads(self):
        """
        定期从讨论区论坛获取最近的帖子，并处理任何尚未在数据库中记录的帖子。
        """
        logger.debug("正在运行提案帖子审计任务...")
        try:
            discussion_channel_id_str = self.bot.config.get("channels", {}).get("discussion")
            if not discussion_channel_id_str:
                logger.warning("讨论频道未配置，跳过审计任务")
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
                async for thread in channel.archived_threads(limit=100):  # 限制在一个合理的数量
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

                async with UnitOfWork(self.bot.db_handler) as uow:
                    proposal = await uow.moderation.get_proposal_by_thread_id(thread.id)

                if not proposal:
                    logger.info(f"审计任务发现一个遗漏的提案帖: {thread.name} ({thread.id})。正在处理...")
                    # 这是一个新的、未处理的帖子。委托给逻辑处理器。
                    await self.logic.handle_new_proposal_thread(thread)
                    await asyncio.sleep(1)  # 短暂延迟以避免在发现很多帖子时达到速率限制

        except Exception as e:
            logger.error(f"提案帖子对账任务中发生意外错误: {e}", exc_info=True)

    @reconcile_missing_threads.before_loop
    async def before_reconciliation_loop(self):
        await self.bot.wait_until_ready()
        logger.info("提案帖子对账任务已准备就绪。")


async def setup(bot: "StellariaPactBot"):
    await bot.add_cog(ThreadReconciliation(bot))