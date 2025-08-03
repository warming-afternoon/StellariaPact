import asyncio
import logging
import random

import discord
from discord.ext import commands, tasks
from zoneinfo import ZoneInfo

from StellariaPact.cogs.Notification.AnnouncementMonitorService import AnnouncementMonitorService
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
        self.discussion_tag_id = self.bot.config["tags"]["discussion"]
        self.executing_tag_id = self.bot.config["tags"]["executing"]
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

    @tasks.loop(minutes=1)
    async def check_announcements(self):
        """
        每分钟检查一次到期的公示。
        """
        logger.debug("正在执行定时任务: 检查到期公示...")
        expired_announcement_dtos = []
        try:
            # 步骤 1: 在一个事务中安全地获取所有过期的公示 DTO
            async with UnitOfWork(self.bot.db_handler) as uow:
                expired_announcement_dtos = await uow.announcements.get_expired_announcements()

            if not expired_announcement_dtos:
                logger.debug("没有找到需要处理的到期公示。")
                return

            logger.info(f"发现 {len(expired_announcement_dtos)} 个到期公示，开始处理...")

        except Exception as e:
            logger.error(f"获取到期公示列表时发生严重错误: {e}", exc_info=True)
            return

        # 遍历 DTO 列表，为每个公示执行独立的原子操作和 API 调用
        for announcement_dto in expired_announcement_dtos:
            try:
                # 在独立的事务中更新数据库
                async with UnitOfWork(self.bot.db_handler) as uow_atomic:
                    await uow_atomic.announcements.mark_announcement_as_finished(
                        announcement_dto.id
                    )
                    monitor_service = AnnouncementMonitorService(uow_atomic.session)
                    await monitor_service.delete_monitors_for_announcement(announcement_dto.id)
                    await uow_atomic.commit()

                logger.debug(f"成功在数据库中将公示 {announcement_dto.id} 标记为已完成。")

                # 数据库操作成功后，执行 Discord API 调用
                await self._notify_announcement_finished(announcement_dto)

            except Exception as e:
                logger.error(
                    f"处理公示 {announcement_dto.id} ({announcement_dto.title}) 时发生错误: {e}",
                    exc_info=True,
                )
                # 单个公示处理失败，记录日志并继续处理下一个

        logger.info("所有到期公示处理完毕。")

    async def _notify_announcement_finished(self, announcement_dto):
        """为单个已完成的公示发送通知并更新标签"""
        try:
            thread = self.bot.get_channel(
                announcement_dto.discussionThreadId
            ) or await self.bot.fetch_channel(announcement_dto.discussionThreadId)

            if not isinstance(thread, discord.Thread):
                logger.error(
                    f"无法为公示 {announcement_dto.id} 找到有效的讨论帖 "
                    f"(ID: {announcement_dto.discussionThreadId})。"
                )
                return

            # 修改标签
            forum_channel = thread.parent
            if isinstance(forum_channel, discord.ForumChannel):
                discussion_tag = discord.utils.get(
                    forum_channel.available_tags, id=self.discussion_tag_id
                )
                executing_tag = discord.utils.get(
                    forum_channel.available_tags, id=self.executing_tag_id
                )

                new_tags = [tag for tag in thread.applied_tags if tag.id != self.discussion_tag_id]
                if executing_tag:
                    new_tags.append(executing_tag)

                new_title = f"[执行中] {announcement_dto.title}"
                await self.bot.api_scheduler.submit(
                    coro=thread.edit(name=new_title, applied_tags=new_tags), priority=7
                )

            # 发送通知
            embed = discord.Embed(
                title=f"公示结束: {announcement_dto.title}",
                description="本次公示已到期",
                color=discord.Color.orange(),
            )
            utc_end_time = announcement_dto.endTime.replace(tzinfo=ZoneInfo("UTC"))
            discord_timestamp = f"<t:{int(utc_end_time.timestamp())}:F>"
            embed.add_field(name="公示截止时间", value=discord_timestamp)
            role_mention = f"<@&{self.stewards_role_id}>"
            await self.bot.api_scheduler.submit(
                coro=thread.send(content=role_mention, embed=embed),
                priority=8,
            )
            # 分发事件
            self.bot.dispatch("announcement_finished", announcement_dto)
        except discord.NotFound:
            logger.error(
                f"讨论帖 (ID: {announcement_dto.discussionThreadId}) 未找到，可能已被删除。跳过API通知"
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
