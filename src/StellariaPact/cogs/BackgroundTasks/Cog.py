import logging

import discord
from discord.ext import commands, tasks
from zoneinfo import ZoneInfo

from StellariaPact.cogs.Notification.AnnouncementService import AnnouncementService
from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger("stellaria_pact.tasks")


class Tasks(commands.Cog):
    """
    后台定时任务。
    Controller 层，负责调度 Service 并与 Discord API 交互。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.announcement_service = AnnouncementService()
        self.announcement_channel_id = self.bot.config["channels"]["discussion"]
        self.in_progress_tag_id = self.bot.config["tags"]["announcement_in_progress"]
        self.finished_tag_id = self.bot.config["tags"]["announcement_finished"]
        self.stewards_role_id = self.bot.config["roles"]["stewards"]

    def cog_unload(self):
        self.check_announcements.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        """
        当 Cog 加载完毕且 Bot 准备就绪后，启动后台任务。
        """
        logger.info("后台任务模块已就绪，启动定时检查。")
        self.check_announcements.start()

    @tasks.loop(minutes=2)
    async def check_announcements(self):
        """
        每5分钟检查一次到期的公示。
        """
        logger.info("正在执行定时任务: 检查到期公示...")

        async with self.bot.db_handler.get_session() as session:
            expired_announcements = await self.announcement_service.get_expired_announcements(
                session
            )

        if not expired_announcements:
            logger.info("没有找到需要处理的到期公示。")
            return

        logger.info(f"发现 {len(expired_announcements)} 个到期公示，正在处理...")
        for announcement in expired_announcements:
            try:
                # 2. 更新数据库状态
                async with self.bot.db_handler.get_session() as session:
                    await self.announcement_service.mark_announcement_as_finished(
                        session, announcement.id
                    )

                # 3. 发送通知
                thread = self.bot.get_channel(
                    announcement.discussionThreadId
                ) or await self.bot.fetch_channel(announcement.discussionThreadId)

                if not isinstance(thread, discord.Thread):
                    logger.error(
                        f"无法为公示 {announcement.id} 找到有效的讨论帖 "
                        f"(ID: {announcement.discussionThreadId})。"
                    )
                    continue

                # 修改标签
                forum_channel = thread.parent
                if isinstance(forum_channel, discord.ForumChannel):
                    finished_tag = discord.utils.get(
                        forum_channel.available_tags, id=self.finished_tag_id
                    )

                    # 从现有标签中移除"公示中"，添加"公示结束"
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
                    description="本次公示已到期，标签已自动更新。",
                    color=discord.Color.orange(),
                )
                # 从数据库获取的 endTime 是一个不带时区信息的(naive)datetime对象，
                # 其数值上等于UTC时间。
                # 在调用 .timestamp() 之前，我们必须先为其附加正确的UTC时区信息，
                # 否则Python会假定它是本地时间，从而导致错误的计算。
                utc_end_time = announcement.endTime.replace(tzinfo=ZoneInfo("UTC"))
                discord_timestamp = f"<t:{int(utc_end_time.timestamp())}:F>"

                embed.add_field(name="公示截止时间", value=discord_timestamp)
                # embed.set_footer(text="请管理组及时跟进后续事宜。")

                role_mention = f"<@&{self.stewards_role_id}>"

                await self.bot.api_scheduler.submit(
                    coro=thread.send(content=role_mention, embed=embed),
                    priority=8,  # 后台任务使用较低优先级
                )

            except discord.NotFound:
                logger.error(
                    f"讨论帖 (ID: {announcement.discussionThreadId}) 未找到，可能已被删除。"
                )
            except Exception:
                logger.exception(f"处理公示 {announcement.id} 时发生未知错误。")

        logger.info("所有到期公示处理完毕。")

    @check_announcements.before_loop
    async def before_check_announcements(self):
        await self.bot.wait_until_ready()


async def setup(bot: StellariaPactBot):
    await bot.add_cog(Tasks(bot))
