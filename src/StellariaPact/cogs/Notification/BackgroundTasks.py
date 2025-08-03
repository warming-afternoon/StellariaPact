import asyncio
import logging
import random
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from StellariaPact.cogs.Notification.AnnouncementMonitorService import \
    AnnouncementMonitorService
from StellariaPact.cogs.Notification.RepostService import RepostService
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.UnitOfWork import UnitOfWork

logger = logging.getLogger("stellaria_pact.notification.tasks")


class BackgroundTasks(commands.Cog):
    """
    负责处理与公示相关的后台定时任务，例如检查到期的公示。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.announcement_channel_id = self.bot.config["channels"]["discussion"]
        self.in_progress_tag_id = self.bot.config["tags"]["announcement_in_progress"]
        self.finished_tag_id = self.bot.config["tags"]["announcement_finished"]
        self.stewards_role_id = self.bot.config["roles"]["stewards"]

    def cog_unload(self):
        self.check_announcements.cancel()
        self.check_reposts.cancel()  # type: ignore

    @commands.Cog.listener()
    async def on_ready(self):
        """
        当 Cog 加载完毕且 Bot 准备就绪后，启动后台任务。
        """
        logger.info("后台任务模块已就绪，启动定时检查。")
        self.check_announcements.start()
        self.check_reposts.start()  # type: ignore

    @tasks.loop(minutes=1)
    async def check_reposts(self):
        """
        每分钟检查一次需要重复播报的公示。
        """
        logger.debug("正在执行定时任务: 检查需要重复播报的公示...")
        try:
            async with UnitOfWork(self.bot.db_handler) as uow:
                monitor_service = AnnouncementMonitorService(uow.session)
                repost_service = RepostService(self.bot, uow.session)

                pending_monitors = await monitor_service.get_pending_reposts()

                if not pending_monitors:
                    logger.debug("没有找到需要重复播报的公示。")
                    return

                logger.info(
                    f"发现 {len(pending_monitors)} 个待处理的重复播报: "
                    f"{[m.id for m in pending_monitors]}"
                )

                for monitor in pending_monitors:
                    monitor_id = monitor.id  # 在事务提交前回显ID，避免惰性加载问题
                    try:
                        logger.debug(f"正在处理监控器 ID: {monitor_id}...")
                        await repost_service.process_single_repost(monitor)
                        await uow.commit()  # 为每个成功的播报提交事务
                        logger.info(f"成功处理并提交了监控器 ID: {monitor_id}")
                    except Exception as e:
                        logger.error(f"处理监控器 ID {monitor_id} 时发生错误: {e}", exc_info=True)
                        await uow.rollback()  # 如果出错则回滚当前监控器的更改

        except Exception as e:
            logger.error(f"检查重复播报任务时发生严重错误: {e}", exc_info=True)

    @tasks.loop(minutes=2)
    async def check_announcements(self):
        """
        每2分钟检查一次到期的公示。
        """
        logger.info("正在执行定时任务: 检查到期公示...")
        processed_announcements = []

        try:
            # --- 步骤 1: 数据库操作 ---
            async with UnitOfWork(self.bot.db_handler) as uow:
                expired_announcements = await uow.announcements.get_expired_announcements()
                if not expired_announcements:
                    logger.debug("没有找到需要处理的到期公示。")
                    return

                logger.info(f"发现 {len(expired_announcements)} 个到期公示，正在更新数据库状态...")
                monitor_service = AnnouncementMonitorService(uow.session)
                for announcement in expired_announcements:
                    try:
                        await uow.announcements.mark_announcement_as_finished(announcement.id)
                        await monitor_service.delete_monitors_for_announcement(announcement.id)
                        processed_announcements.append(announcement)
                    except Exception:
                        logger.exception(
                            f"更新公示 {announcement.id} ({announcement.title}) 数据库状态时出错"
                        )

                if processed_announcements:
                    logger.info(
                        f"成功在数据库中将 {len(processed_announcements)} 个公示标记为已完成。"
                    )

        except Exception as e:
            logger.error(f"检查到期公示的数据库操作阶段发生严重错误: {e}", exc_info=True)
            return  # 如果数据库出错，则不继续执行 API 调用

        # --- 步骤 2: Discord API 调用 ---
        if not processed_announcements:
            return

        logger.info(f"正在为 {len(processed_announcements)} 个已完成的公示执行 API 调用...")
        api_tasks = [
            self._notify_announcement_finished(announcement)
            for announcement in processed_announcements
        ]
        results = await asyncio.gather(*api_tasks, return_exceptions=True)

        for result, announcement in zip(results, processed_announcements):
            if isinstance(result, Exception):
                logger.exception(
                    f"为公示 {announcement.id} ({announcement.title}) 执行 API 调用时发生错误"
                )

        logger.info("所有到期公示处理完毕。")

    async def _notify_announcement_finished(self, announcement):
        """为单个已完成的公示发送通知并更新标签"""
        try:
            thread = self.bot.get_channel(
                announcement.discussionThreadId
            ) or await self.bot.fetch_channel(announcement.discussionThreadId)

            if not isinstance(thread, discord.Thread):
                logger.error(
                    f"无法为公示 {announcement.id} 找到有效的讨论帖 "
                    f"(ID: {announcement.discussionThreadId})。"
                )
                return

            # 修改标签
            forum_channel = thread.parent
            if isinstance(forum_channel, discord.ForumChannel):
                finished_tag = discord.utils.get(
                    forum_channel.available_tags, id=self.finished_tag_id
                )
                new_tags = [
                    tag for tag in thread.applied_tags if tag.id != self.in_progress_tag_id
                ]
                if finished_tag:
                    new_tags.append(finished_tag)
                await self.bot.api_scheduler.submit(
                    coro=thread.edit(applied_tags=new_tags), priority=7
                )

            # 发送通知
            embed = discord.Embed(
                title=f"公示结束: {announcement.title}",
                description="本次公示已到期",
                color=discord.Color.orange(),
            )
            utc_end_time = announcement.endTime.replace(tzinfo=ZoneInfo("UTC"))
            discord_timestamp = f"<t:{int(utc_end_time.timestamp())}:F>"
            embed.add_field(name="公示截止时间", value=discord_timestamp)
            role_mention = f"<@&{self.stewards_role_id}>"
            await self.bot.api_scheduler.submit(
                coro=thread.send(content=role_mention, embed=embed),
                priority=8,
            )
        except discord.NotFound:
            logger.error(
                f"讨论帖 (ID: {announcement.discussionThreadId}) 未找到，可能已被删除。跳过API通知"
            )
        except Exception:
            # 异常将在 gather 中被捕获和记录
            raise

    @check_announcements.before_loop
    async def before_check_announcements(self):
        await self.bot.wait_until_ready()
        # 增加随机延迟以错开任务启动时间
        await asyncio.sleep(random.randint(0, 30))

    @check_reposts.before_loop
    async def before_check_reposts(self):
        await self.bot.wait_until_ready()
        # 增加随机延迟以错开任务启动时间
        await asyncio.sleep(random.randint(0, 15))
