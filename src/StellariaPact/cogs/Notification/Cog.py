import asyncio
import logging
import re
from datetime import datetime
from typing import Literal, Optional
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from StellariaPact.cogs.Notification.dto.AdjustTimeDto import AdjustTimeDto
from StellariaPact.cogs.Notification.qo.CreateAnnouncementQo import CreateAnnouncementQo
from StellariaPact.cogs.Notification.views.AnnouncementEmbedBuilder import AnnouncementEmbedBuilder
from StellariaPact.cogs.Notification.views.AnnouncementModal import AnnouncementModal
from StellariaPact.share.auth import MissingRole, RoleGuard
from StellariaPact.share import (
    DiscordUtils,
    StellariaPactBot,
    StringUtils,
    TimeUtils,
    UnitOfWork,
    safeDefer,
)

logger = logging.getLogger(__name__)


class Notification(commands.Cog):
    """
    处理所有与通知相关的命令，例如发布公示。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.discussion_channel_id = self.bot.config["channels"]["discussion"]
        self.broadcast_channel_ids = self.bot.config["channels"]["broadcast"]
        self.discussion_tag_id = self.bot.config["tags"]["discussion"]

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
                        "发生了一个未知错误，请联系技术员。", ephemeral=True
                    ),
                    priority=1,
                )

    @app_commands.command(
        name="发布公示", description="[管理组/议事督导/执行监理]发布一个新的社区公示"
    )
    @RoleGuard.requireRoles("stewards", "councilModerator", "executionAuditor")
    @app_commands.rename(
        message_threshold="消息数阈值",
        time_interval_minutes="时间间隔阈值",
        enable_reposting="开启公示宣传",
        auto_execute="结束时自动进入执行",
    )
    @app_commands.describe(
        message_threshold="触发重复公示的消息数量 (默认: 1000)",
        time_interval_minutes="触发重复公示的时间间隔分钟数 (默认: 60)",
        enable_reposting="是否开启到期前反复宣传的功能 (默认: 开启)",
        auto_execute="[管理组] 是否自动变更为执行中 (默认: 是)",
    )
    async def publish_announcement(
        self,
        interaction: discord.Interaction,
        auto_execute: bool = True,
        message_threshold: int = 1000,
        time_interval_minutes: int = 60,
        enable_reposting: bool = True,
    ):
        """
        处理 /发布公示 命令, 弹出一个模态窗口来收集信息。
        """
        # 权限检查
        if auto_execute and not RoleGuard.hasRoles(interaction, "stewards"):
            await self.bot.api_scheduler.submit(
                coro=interaction.response.send_message(
                    "权限不足：只有 `管理组` 才能发布“自动进入执行”的公示。\n"
                    "请将 `结束时自动进入执行` 选项设置为 `False` 后重试。",
                    ephemeral=True,
                ),
                priority=1,
            )
            return

        modal = AnnouncementModal(
            bot=self.bot,
            notification_cog=self,
            enable_reposting=enable_reposting,
            message_threshold=message_threshold,
            time_interval_minutes=time_interval_minutes,
            auto_execute=auto_execute,
        )
        await self.bot.api_scheduler.submit(
            coro=interaction.response.send_modal(modal), priority=1
        )

    async def create_announcement_workflow(
        self,
        interaction: discord.Interaction,
        title: str,
        content: str,
        duration_hours: int,
        link: Optional[str],
        auto_execute: bool,
        enable_reposting: bool,
        message_threshold: int,
        time_interval_minutes: int,
    ):
        """处理创建公示的工作流"""
        await safeDefer(interaction)
        thread = None
        try:
            # --- 计算时间 ---
            start_time_utc = datetime.now(ZoneInfo("UTC"))
            timezone = self.bot.config.get("timezone", "UTC")
            end_time = self.bot.time_utils.get_utc_end_time(
                duration_hours, timezone, start_time=start_time_utc
            )
            utc_aware_end_time = end_time.replace(tzinfo=ZoneInfo("UTC"))
            end_time_timestamp = int(utc_aware_end_time.timestamp())
            discord_timestamp = f"<t:{end_time_timestamp}:F> (<t:{end_time_timestamp}:R>)"

            # --- 步骤 1: 获取或创建讨论帖 ---
            if link:
                thread_id = StringUtils.extract_thread_id_from_url(link)
                if not thread_id:
                    raise ValueError("提供的链接格式不正确，无法识别帖子ID。")
                thread = await DiscordUtils.fetch_thread(self.bot, thread_id)
                if not thread:
                    raise ValueError(f"无法根据链接找到ID为 {thread_id} 的帖子。")
            else:
                discussion_channel = self.bot.get_channel(self.discussion_channel_id)
                if not isinstance(discussion_channel, discord.ForumChannel):
                    raise TypeError("配置的讨论区频道不是有效的论坛频道。")

                thread_content = AnnouncementEmbedBuilder.create_thread_content(
                    title=title,
                    content=content,
                    discord_timestamp=discord_timestamp,
                    author_id=interaction.user.id,
                )
                thread_name = f"[公示中] {title}"

                initial_tags = DiscordUtils.calculate_new_tags(
                    current_tags=[],
                    forum_tags=discussion_channel.available_tags,
                    config=self.bot.config,
                    target_tag_name="discussion",
                )

                thread_creation_result = await self.bot.api_scheduler.submit(
                    coro=discussion_channel.create_thread(
                        name=thread_name, content=thread_content, applied_tags=initial_tags or []
                    ),
                    priority=5,
                )
                thread = thread_creation_result.thread

            # --- 步骤 2: 数据库操作 ---
            async with UnitOfWork(self.bot.db_handler) as uow:
                qo = CreateAnnouncementQo(
                    discussion_thread_id=thread.id,
                    announcer_id=interaction.user.id,
                    title=title,
                    content=content,
                    end_time=end_time,
                    auto_execute=auto_execute,
                )
                announcement = await uow.announcements.create_announcement(qo)

                if enable_reposting:
                    if not announcement.id:
                        raise ValueError("Announcement ID is missing after creation.")
                    await uow.announcement_monitors.create_monitors_for_announcement(
                        announcement_id=announcement.id,
                        channel_ids=self.broadcast_channel_ids,
                        message_threshold=message_threshold,
                        time_interval_minutes=time_interval_minutes,
                    )
                await uow.commit()

            # --- 步骤 3: 广播 ---
            broadcast_embed = AnnouncementEmbedBuilder.create_announcement_embed(
                title=title,
                content=content,
                thread_url=thread.jump_url,
                discord_timestamp=discord_timestamp,
                author=interaction.user,
                start_time_utc=start_time_utc,
                is_repost=False,
            )
            broadcast_tasks = [
                self.bot.api_scheduler.submit(coro=channel.send(embed=broadcast_embed), priority=5)
                for channel_id in self.broadcast_channel_ids
                if isinstance(channel := self.bot.get_channel(channel_id), discord.TextChannel)
            ]
            await asyncio.gather(*broadcast_tasks, return_exceptions=True)

            # --- 最终确认 ---
            await self.bot.api_scheduler.submit(
                coro=interaction.followup.send(
                    f"✅ 公示 **{title}** 已成功发布！\n讨论帖: {thread.mention}",
                    ephemeral=True,
                ),
                priority=1,
            )

        except Exception as e:
            logger.error(f"发布公示工作流失败: {e}", exc_info=True)
            error_message = f"发布公示时发生未知错误，请联系技术员。\n`{e}`"
            if isinstance(e, discord.Forbidden):
                error_message = "机器人可能缺少创建帖子、获取帖子或应用标签的权限。"
            elif isinstance(e, (TypeError, ValueError)):
                error_message = f"配置或输入错误: {e}"

            # 在新建帖子失败时，不显示 thread.mention
            if thread and not link:
                error_message += f"\n\n讨论帖 {thread.mention} 已创建，但后续操作失败。"

            await self.bot.api_scheduler.submit(
                coro=interaction.followup.send(error_message, ephemeral=True), priority=1
            )

    @app_commands.command(
        name="修改公示时间", description="[管理组/议事督导/执行监理] 修改当前公示的持续时间"
    )
    @app_commands.rename(operation="操作", hours="小时数")
    @app_commands.describe(operation="选择要执行的操作", hours="要调整的小时数")
    @RoleGuard.requireRoles("stewards", "councilModerator", "executionAuditor")
    async def modify_announcement_time(
        self,
        interaction: discord.Interaction,
        operation: Literal["延长", "缩短"],
        hours: int,
    ):
        await safeDefer(interaction, ephemeral=True)

        if hours <= 0:
            await self.bot.api_scheduler.submit(
                coro=interaction.followup.send("小时数必须是正整数。", ephemeral=True),
                priority=1,
            )
            return
        if not isinstance(interaction.channel, discord.Thread):
            await self.bot.api_scheduler.submit(
                coro=interaction.followup.send("此命令必须在公示讨论帖内使用。", ephemeral=True),
                priority=1,
            )
            return

        try:
            time_change_hours = hours if operation == "延长" else -hours
            if not isinstance(interaction.channel, discord.Thread):
                return

            result = await self._update_announcement_time_in_db(
                interaction, interaction.channel, time_change_hours
            )
            if not result:
                return

            new_ts_timestamp = int(result.new_end_time.replace(tzinfo=ZoneInfo("UTC")).timestamp())
            new_ts_string = f"<t:{new_ts_timestamp}:F> (<t:{new_ts_timestamp}:R>)"

            await self._update_starter_message_timestamp(interaction.channel, new_ts_string)

            old_ts = f"<t:{int(result.old_end_time.timestamp())}:F> (<t:{int(result.old_end_time.timestamp())}:R>)"
            embed = AnnouncementEmbedBuilder.create_time_modification_embed(
                interaction_user=interaction.user,
                operation=operation,
                hours=hours,
                old_timestamp=old_ts,
                new_timestamp=new_ts_string,
            )
            await self.bot.api_scheduler.submit(
                coro=interaction.channel.send(embed=embed), priority=5
            )
            await self.bot.api_scheduler.submit(
                coro=interaction.followup.send("公示时间已成功修改。", ephemeral=True),
                priority=1,
            )

        except Exception as e:
            logger.error(f"修改公示时间时发生错误: {e}", exc_info=True)
            await self.bot.api_scheduler.submit(
                coro=interaction.followup.send(
                    "修改公示时间时发生未知错误，请联系技术员。", ephemeral=True
                ),
                priority=1,
            )

    async def _update_announcement_time_in_db(
        self,
        interaction: discord.Interaction,
        thread: discord.Thread,
        time_change_hours: int,
    ) -> Optional[AdjustTimeDto]:
        """
        在数据库中更新公示的结束时间。

        Args:
            interaction: 触发命令的 Discord 交互对象。
            thread: 公示讨论帖的 Discord 线程对象。
            time_change_hours: 要调整的小时数（正数表示延长，负数表示缩短）。

        Returns:
            如果成功，返回包含新旧结束时间的 AdjustTimeDto；如果失败（例如帖子无效、公示已结束等），
            则向用户发送错误消息并返回 None。
        """
        async with UnitOfWork(self.bot.db_handler) as uow:
            announcement = await uow.announcements.get_by_thread_id(thread.id)
            if not announcement:
                await self.bot.api_scheduler.submit(
                    coro=interaction.followup.send(
                        "这里不是一个有效的公示讨论帖。", ephemeral=True
                    ),
                    priority=1,
                )
                return None

            if announcement.status != 1:
                await self.bot.api_scheduler.submit(
                    coro=interaction.followup.send("该公示已结束，无法修改时间。", ephemeral=True),
                    priority=1,
                )
                return None

            if announcement.id is None:
                logger.error(f"Announcement {announcement} has no ID")
                await self.bot.api_scheduler.submit(
                    coro=interaction.followup.send("公示数据异常，请联系技术员。", ephemeral=True),
                    priority=1,
                )
                return None

            old_end_time_utc = announcement.end_time.replace(tzinfo=ZoneInfo("UTC"))
            new_end_time = TimeUtils.get_utc_end_time(
                time_change_hours,
                self.bot.config.get("timezone", "UTC"),
                start_time=old_end_time_utc,
            )
            new_end_time_utc = new_end_time.replace(tzinfo=ZoneInfo("UTC"))

            await uow.announcements.update_end_time(announcement.id, new_end_time_utc)
            adjustTimeDto = AdjustTimeDto(
                announcement_id=announcement.id,
                old_end_time=old_end_time_utc,
                new_end_time=new_end_time_utc,
            )
            await uow.commit()

            return adjustTimeDto

    async def _update_starter_message_timestamp(self, thread: discord.Thread, new_ts_string: str):
        """
        更新公示讨论帖首楼消息中的截止时间戳。

        仅当首楼消息由机器人自己发布，并且包含标准格式的截止时间字符串时，才会进行替换。

        Args:
            thread: 公示讨论帖的 Discord 线程对象。
            new_ts_string: 新的 Discord 时间戳字符串，格式为 "<t:...:F> (<t:...:R>)"。
        """
        try:
            starter_message = await self.bot.api_scheduler.submit(
                coro=thread.fetch_message(thread.id),
                priority=3,
            )

            if not self.bot.user or starter_message.author.id != self.bot.user.id:
                logger.info(f"帖子 {thread.id} 首楼不是由机器人发布的，跳过编辑。")
                return

            deadline_pattern = re.compile(
                r"(\*\*公示截止时间:\s*\*\*\s*)<t:\d+:[fF]>\s*\(<t:\d+:[rR]>\)"
            )
            if deadline_pattern.search(starter_message.content):
                new_deadline = f"**公示截止时间:** {new_ts_string}"
                new_content = deadline_pattern.sub(new_deadline, starter_message.content, count=1)
                await self.bot.api_scheduler.submit(
                    coro=starter_message.edit(content=new_content), priority=5
                )
                logger.info(f"成功更新帖子 {thread.id} 首楼的时间戳。")
            else:
                logger.info(f"帖子 {thread.id} 首楼未找到标准截止时间格式，跳过编辑。")

        except (discord.NotFound, discord.Forbidden) as e:
            logger.warning(f"无法获取或编辑帖子 {thread.id} 的首楼消息: {e}")
