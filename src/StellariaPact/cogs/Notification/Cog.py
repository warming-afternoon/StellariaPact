import asyncio
import logging
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands
from zoneinfo import ZoneInfo

from StellariaPact.cogs.Notification.AnnouncementService import AnnouncementService
from StellariaPact.cogs.Notification.views.AnnouncementModal import AnnouncementModal
from StellariaPact.share.auth.MissingRole import MissingRole
from StellariaPact.share.auth.RoleGuard import RoleGuard
from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.TimeUtils import TimeUtils

logger = logging.getLogger("stellaria_pact.notification")


class Notification(commands.Cog):
    """
    处理所有与通知相关的命令，例如发布公示。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.announcement_service = AnnouncementService()

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        """
        这个 Cog 的局部错误处理器。
        """
        original_error = getattr(error, "original", error)
        if isinstance(original_error, MissingRole):
            # 如果是 MissingRole 错误，并且交互尚未响应，就发送一个仅用户可见的消息
            if not interaction.response.is_done():
                await self.bot.api_scheduler.submit(
                    coro=interaction.response.send_message(str(original_error), ephemeral=True),
                    priority=1,
                )
        else:
            # 对于其他错误，记录日志并通知用户
            logger.error(f"在 Notification Cog 中发生未处理的错误: {error}", exc_info=True)
            if not interaction.response.is_done():
                await self.bot.api_scheduler.submit(
                    coro=interaction.response.send_message(
                        "发生了一个未知错误，请联系管理员。", ephemeral=True
                    ),
                    priority=1,
                )

    @app_commands.command(name="发布公示", description="通过表单发布一个新的社区公示")
    @RoleGuard.requireRoles("stewards")
    async def publish_announcement(self, interaction: discord.Interaction):
        """
        处理 /发布公示 命令, 弹出一个模态窗口来收集信息。
        """
        modal = AnnouncementModal(self.bot)
        await interaction.response.send_modal(modal)

    @app_commands.command(name="修改公示时间", description="修改当前公示的持续时间")
    @app_commands.rename(operation="操作", hours="小时数")
    @app_commands.describe(operation="选择要执行的操作", hours="要调整的小时数")
    @RoleGuard.requireRoles("stewards")
    async def modify_announcement_time(
        self,
        interaction: discord.Interaction,
        operation: Literal["延长", "缩短"],
        hours: int,
    ):
        """
        处理 /修改公示时间 命令，允许管理者修改公示的结束时间。
        """
        await self.bot.api_scheduler.submit(safeDefer(interaction), priority=1)

        if hours <= 0:
            await self.bot.api_scheduler.submit(
                interaction.followup.send("小时数必须是正整数。", ephemeral=True), priority=1
            )
            return

        thread_id = interaction.channel_id
        if not thread_id:
            await self.bot.api_scheduler.submit(
                interaction.followup.send("无法在此频道中执行此操作。", ephemeral=True),
                priority=1,
            )
            return

        target_tz = self.bot.config.get("timezone", "UTC")

        async with self.bot.db_handler.get_session() as session:
            announcement = await self.announcement_service.get_by_thread_id(
                session, thread_id
            )

            if not announcement:
                await self.bot.api_scheduler.submit(
                    interaction.followup.send("此频道不是一个有效的公示讨论帖。", ephemeral=True),
                    priority=1,
                )
                return

            if announcement.status != 0:
                await self.bot.api_scheduler.submit(
                    interaction.followup.send("该公示已结束，无法修改时间。", ephemeral=True),
                    priority=1,
                )
                return

            old_end_time_utc = announcement.endTime.replace(tzinfo=ZoneInfo("UTC"))
            time_change_hours = hours if operation == "延长" else -hours
            new_end_time = TimeUtils.get_utc_end_time(
                time_change_hours, target_tz, start_time=old_end_time_utc
            )


            db_update_task = self.announcement_service.update_end_time(
                session, announcement.id, new_end_time
            )

            embed = discord.Embed(
                title="公示时间已更新",
                description=f"{interaction.user.mention} 将公示截止时间 **{operation}** 了 {hours} 小时",
                color=discord.Color.blue(),
            )
            embed.add_field(
                name="原截止时间", value=f"<t:{int(old_end_time_utc.timestamp())}:F>", inline=False
            )
            embed.add_field(
                name="新截止时间",
                value=f"<t:{int(new_end_time.replace(tzinfo=ZoneInfo('UTC')).timestamp())}:F>",
                inline=False,
            )
            embed.set_footer(text=f"操作人: {interaction.user.display_name}")

            public_notification_task = None
            if isinstance(interaction.channel, (discord.TextChannel, discord.Thread)):
                public_notification_task = self.bot.api_scheduler.submit(
                    interaction.channel.send(embed=embed),
                    priority=5,
                )
            else:
                logger.warning(
                    f"无法在频道 {interaction.channel_id} (类型: {type(interaction.channel)}) 中发送消息，因为它不是文本频道或帖子。"
                )

            tasks_to_run = [db_update_task]
            if public_notification_task:
                tasks_to_run.append(public_notification_task)

            results = await asyncio.gather(*tasks_to_run, return_exceptions=True)

            # 分析结果并构建反馈
            error_messages = []
            db_result = results[0]
            if isinstance(db_result, Exception):
                error_messages.append("数据库更新失败。")
                logger.error(f"修改公示时间时，数据库更新失败: {db_result}", exc_info=True)

            if public_notification_task:
                notification_result = results[1]
                if isinstance(notification_result, Exception):
                    error_messages.append("公开通知发送失败。")
                    logger.error(f"修改公示时间时，公开通知发送失败: {notification_result}", exc_info=True)

            # 发送最终的用户反馈
            if not error_messages:
                feedback_message = "公示时间已成功修改。"
            else:
                feedback_message = "操作出现问题：\n- " + "\n- ".join(error_messages) + "\n请联系技术员。"

            await self.bot.api_scheduler.submit(
                interaction.followup.send(feedback_message, ephemeral=True), priority=1
            )


async def setup(bot: StellariaPactBot):
    await bot.add_cog(Notification(bot))
