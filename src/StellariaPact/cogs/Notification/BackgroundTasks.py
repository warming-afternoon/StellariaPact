import asyncio
import logging
import random
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands, tasks

from StellariaPact.cogs.Notification.AnnouncementMonitorService import AnnouncementMonitorService
from StellariaPact.cogs.Notification.dto.AnnouncementDto import AnnouncementDto
from StellariaPact.cogs.Notification.RepostService import RepostService
from StellariaPact.models.AnnouncementChannelMonitor import AnnouncementChannelMonitor
from StellariaPact.share.DiscordUtils import DiscordUtils
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
        pending_monitor_ids = []
        try:
            # 在一个简短的事务中安全地获取所有待处理的监控ID
            async with UnitOfWork(self.bot.db_handler) as uow:
                monitor_service = AnnouncementMonitorService(uow.session)
                pending_monitors = await monitor_service.get_pending_reposts()
                pending_monitor_ids = [m.id for m in pending_monitors if m.id is not None]

            if not pending_monitor_ids:
                logger.debug("没有找到需要重复播报的公示。")
                return

            logger.info(
                f"发现 {len(pending_monitor_ids)} 个待处理的重复播报: {pending_monitor_ids}"
            )

        except Exception as e:
            logger.error(f"获取待处理播报列表时发生严重错误: {e}", exc_info=True)
            return

        # 遍历ID列表，为每个监控执行独立的原子操作
        for monitor_id in pending_monitor_ids:
            try:
                logger.debug(f"正在处理监控器 ID: {monitor_id}...")
                async with UnitOfWork(self.bot.db_handler) as uow_atomic:
                    repost_service = RepostService(self.bot, uow_atomic.session)
                    # 在新的事务中重新获取monitor对象
                    monitor_to_process = await uow_atomic.session.get(
                        AnnouncementChannelMonitor, monitor_id
                    )
                    if not monitor_to_process:
                        logger.warning(f"在处理前无法找到监控器 ID: {monitor_id}，可能已被处理。")
                        continue

                    await repost_service.process_single_repost(monitor_to_process)
                    await uow_atomic.commit()
                logger.debug(f"成功处理并提交了监控器 ID: {monitor_id}")

            except Exception as e:
                logger.error(f"处理监控器 ID {monitor_id} 时发生错误: {e}", exc_info=True)
                # 单个任务失败，记录日志并继续处理下一个

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

    async def _notify_announcement_finished(self, announcement_dto: AnnouncementDto):
        """为单个已完成的公示发送通知并更新标签"""
        try:
            thread = self.bot.get_channel(
                announcement_dto.discussion_thread_id
            ) or await self.bot.fetch_channel(announcement_dto.discussion_thread_id)

            if not isinstance(thread, discord.Thread):
                logger.error(
                    f"无法为公示 {announcement_dto.id} 找到有效的讨论帖 "
                    f"(ID: {announcement_dto.discussion_thread_id})。"
                )
                return

            if announcement_dto.auto_execute:
                # 自动执行
                embed_title = f"公示结束: {announcement_dto.title}"
                embed_description = "本次公示已到期，现已自动进入执行阶段。"
                color = discord.Color.green()

                # 修改标签和标题
                forum_channel = thread.parent
                new_title = f"[执行中] {announcement_dto.title}"

                if isinstance(forum_channel, discord.ForumChannel):
                    new_tags = DiscordUtils.calculate_new_tags(
                        current_tags=thread.applied_tags,
                        forum_tags=forum_channel.available_tags,
                        config=self.bot.config,
                        target_tag_name="executing",
                    )
                    if new_tags is not None:
                        await self.bot.api_scheduler.submit(
                            coro=thread.edit(name=new_title, applied_tags=new_tags),
                            priority=7,
                        )
                    else:
                        await self.bot.api_scheduler.submit(
                            coro=thread.edit(name=new_title), priority=7
                        )

            else:
                # 非自动执行
                embed_title = f"公示期结束: {announcement_dto.title}"
                embed_description = "本次公示已到期"
                color = discord.Color.dark_grey()

            # 发送通知
            embed = discord.Embed(
                title=embed_title,
                description=embed_description,
                color=color,
            )
            utc_end_time = announcement_dto.end_time.replace(tzinfo=ZoneInfo("UTC"))
            discord_timestamp = (
                f"<t:{int(utc_end_time.timestamp())}:F>(<t:{int(utc_end_time.timestamp())}:R>)"
            )
            embed.add_field(name="公示截止时间", value=discord_timestamp)

            # content = f"<@&{self.stewards_role_id}>"
            content = ""
            await self.bot.api_scheduler.submit(
                coro=thread.send(content=content, embed=embed),
                priority=8,
            )

            if announcement_dto.auto_execute:
                self.bot.dispatch("announcement_finished", announcement_dto)
        except discord.NotFound:
            logger.error(
                (
                    f"讨论帖 (ID: {announcement_dto.discussion_thread_id}) 未找到，"
                    "可能已被删除。跳过API通知"
                )
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
