import asyncio
import logging
from datetime import datetime
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands
from zoneinfo import ZoneInfo

from StellariaPact.cogs.Notification.qo.CreateAnnouncementQo import CreateAnnouncementQo
from StellariaPact.cogs.Notification.views.AnnouncementEmbedBuilder import AnnouncementEmbedBuilder
from StellariaPact.cogs.Notification.views.AnnouncementModal import AnnouncementModal
from StellariaPact.share.auth.MissingRole import MissingRole
from StellariaPact.share.auth.RoleGuard import RoleGuard
from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot
from StellariaPact.share.TimeUtils import TimeUtils
from StellariaPact.share.UnitOfWork import UnitOfWork

logger = logging.getLogger("stellaria_pact.notification")


class Notification(commands.Cog):
    """
    处理所有与通知相关的命令，例如发布公示。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.discussion_channel_id = self.bot.config["channels"]["discussion"]
        self.broadcast_channel_ids = self.bot.config["channels"]["broadcast"]
        self.in_progress_tag_id = self.bot.config["tags"]["announcement_in_progress"]

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        """
        这个 Cog 的局部错误处理器。
        """
        original_error = getattr(error, "original", error)
        if isinstance(original_error, MissingRole):
            if not interaction.response.is_done():
                await self.bot.api_scheduler.submit(
                    coro=interaction.response.send_message(str(original_error), ephemeral=True),
                    priority=1,
                )
        else:
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
    @app_commands.rename(
        enable_reposting="开启重复公示",
        message_threshold="消息数阈值",
        time_interval_minutes="时间间隔分钟数",
    )
    @app_commands.describe(
        enable_reposting="是否开启到期前反复宣传的功能 (默认: 开启)",
        message_threshold="触发重复公示的消息数量 (默认: 1000)",
        time_interval_minutes="触发重复公示的时间间隔分钟数 (默认: 60)",
    )
    async def publish_announcement(
        self,
        interaction: discord.Interaction,
        enable_reposting: bool = True,
        message_threshold: int = 1000,
        time_interval_minutes: int = 60,
    ):
        """
        处理 /发布公示 命令, 弹出一个模态窗口来收集信息。
        """
        modal = AnnouncementModal(
            bot=self.bot,
            notification_cog=self,
            enable_reposting=enable_reposting,
            message_threshold=message_threshold,
            time_interval_minutes=time_interval_minutes,
        )
        await interaction.response.send_modal(modal)

    async def create_announcement_workflow(
        self,
        interaction: discord.Interaction,
        title: str,
        content: str,
        end_time: datetime,
        thread_content: str,
        discord_timestamp: str,
        start_time_utc: datetime,
        enable_reposting: bool,
        message_threshold: int,
        time_interval_minutes: int,
    ):
        """
        处理创建公示的工作流
        """
        thread = None
        try:
            # --- 步骤 1: API 调用 - 创建讨论帖 ---
            discussion_channel = self.bot.get_channel(self.discussion_channel_id)
            if not isinstance(discussion_channel, discord.ForumChannel):
                raise TypeError("配置的讨论区频道不是有效的论坛频道。")

            target_tag = discord.utils.get(
                discussion_channel.available_tags, id=self.in_progress_tag_id
            )
            if not target_tag:
                raise ValueError("在论坛频道中找不到配置的“公示中”标签。")

            thread_name = f"【公示】{title}"
            thread_creation_result = await discussion_channel.create_thread(
                name=thread_name, content=thread_content, applied_tags=[target_tag]
            )
            thread = thread_creation_result.thread

            # --- 步骤 2: 数据库操作 ---
            async with UnitOfWork(self.bot.db_handler) as uow:
                qo = CreateAnnouncementQo(
                    discussionThreadId=thread.id,
                    announcerId=interaction.user.id,
                    title=title,
                    content=content,
                    endTime=end_time,
                )
                announcement_dto = await uow.announcements.create_announcement(qo)

                # 如果开启了重复公示，则创建监控记录
                if enable_reposting:
                    await uow.announcement_monitors.create_monitors_for_announcement(
                        announcement_id=announcement_dto.id,
                        channel_ids=self.broadcast_channel_ids,
                        message_threshold=message_threshold,
                        time_interval_minutes=time_interval_minutes,
                    )

            # --- 步骤 3: API 调用 - 广播 ---
            broadcast_embed = AnnouncementEmbedBuilder.create_broadcast_embed(
                title=title,
                content=content,
                thread_url=thread.jump_url,
                discord_timestamp=discord_timestamp,
                author=interaction.user,
                start_time_utc=start_time_utc,
            )
            broadcast_tasks = [
                self.bot.api_scheduler.submit(coro=channel.send(embed=broadcast_embed), priority=5)
                for channel_id in self.broadcast_channel_ids
                if isinstance(channel := self.bot.get_channel(channel_id), discord.TextChannel)
            ]
            await asyncio.gather(*broadcast_tasks, return_exceptions=True)  # 忽略广播的个别错误

            # --- 步骤 4: 最终确认 ---
            await interaction.followup.send(
                f"✅ 公示 **{title}** 已成功发布！\n讨论帖已在 {thread.mention} 创建。",
                ephemeral=True,
            )

        except Exception as e:
            logger.error(f"发布公示工作流失败: {e}", exc_info=True)
            error_message = f"发布公示时发生未知错误，请联系技术员。\n`{e}`"
            if isinstance(e, discord.Forbidden):
                error_message = "机器人可能缺少创建帖子或应用标签的权限。"
            elif isinstance(e, (TypeError, ValueError)):
                error_message = f"配置错误: {e}"

            if thread:
                error_message += f"\n\n讨论帖 {thread.mention} 已创建，但后续操作失败。"

            await interaction.followup.send(error_message, ephemeral=True)

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
        await safeDefer(interaction)

        if hours <= 0:
            await interaction.followup.send("小时数必须是正整数。", ephemeral=True)
            return
        if not interaction.channel:
            await interaction.followup.send("此命令必须在频道内使用。", ephemeral=True)
            return

        try:
            # --- 数据库操作 ---
            async with UnitOfWork(self.bot.db_handler) as uow:
                announcement = await uow.announcements.get_by_thread_id(interaction.channel.id)
                if not announcement:
                    await interaction.followup.send(
                        "此频道不是一个有效的公示讨论帖。", ephemeral=True
                    )
                    return
                if announcement.status != 1:
                    await interaction.followup.send("该公示已结束，无法修改时间。", ephemeral=True)
                    return

                old_end_time_utc = announcement.endTime.replace(tzinfo=ZoneInfo("UTC"))
                time_change_hours = hours if operation == "延长" else -hours
                new_end_time = TimeUtils.get_utc_end_time(
                    time_change_hours,
                    self.bot.config.get("timezone", "UTC"),
                    start_time=old_end_time_utc,
                )

                await uow.announcements.update_end_time(announcement.id, new_end_time)

                # --- API 调用 ---
                old_ts = f"<t:{int(old_end_time_utc.timestamp())}:F>"
                new_ts = f"<t:{int(new_end_time.replace(tzinfo=ZoneInfo('UTC')).timestamp())}:F>"
                embed = AnnouncementEmbedBuilder.create_time_modification_embed(
                    interaction_user=interaction.user,
                    operation=operation,
                    hours=hours,
                    old_timestamp=old_ts,
                    new_timestamp=new_ts,
                )

                if isinstance(
                    interaction.channel,
                    (discord.TextChannel, discord.Thread, discord.VoiceChannel),
                ):
                    await self.bot.api_scheduler.submit(
                        interaction.channel.send(embed=embed), priority=5
                    )
                    await interaction.followup.send("公示时间已成功修改。", ephemeral=True)
                else:
                    logger.warning(
                        f"无法在频道 {interaction.channel_id} (类型: {type(interaction.channel)}) "
                        "中发送时间修改通知，因为它不是一个有效的消息频道。"
                    )
                    # 即使无法发送通知，也应告知用户操作已成功
                    await interaction.followup.send(
                        "数据库中的公示时间已成功修改，但无法在此频道发送公开通知。",
                        ephemeral=True,
                    )

        except Exception as e:
            logger.error(f"修改公示时间时发生错误: {e}", exc_info=True)
            await interaction.followup.send(
                "修改公示时间时发生未知错误，请联系技术员。", ephemeral=True
            )
