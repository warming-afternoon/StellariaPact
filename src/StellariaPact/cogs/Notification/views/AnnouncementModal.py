import logging
from datetime import datetime
from typing import TYPE_CHECKING

import discord
from discord import ui
from zoneinfo import ZoneInfo

from StellariaPact.share.StellariaPactBot import StellariaPactBot

from .AnnouncementEmbedBuilder import AnnouncementEmbedBuilder

if TYPE_CHECKING:
    from StellariaPact.cogs.Notification.Cog import Notification

logger = logging.getLogger("stellaria_pact.notification")


class AnnouncementModal(ui.Modal, title="发布新公示"):
    """
    用于收集新公示信息的模态窗口。
    """

    title_input = ui.TextInput(
        label="公示标题",
        placeholder="请输入公示的标题",
        style=discord.TextStyle.short,
        required=True,
        max_length=100,
    )

    content_input = ui.TextInput(
        label="公示内容",
        placeholder="请输入公示的具体内容，支持 Markdown 格式。",
        style=discord.TextStyle.long,
        required=True,
        max_length=4000,
    )

    def __init__(
        self,
        bot: StellariaPactBot,
        notification_cog: "Notification",
        enable_reposting: bool,
        message_threshold: int,
        time_interval_minutes: int,
        duration_hours: int,
    ):
        super().__init__(timeout=1800)
        self.bot = bot
        self.cog = notification_cog
        self.enable_reposting = enable_reposting
        self.message_threshold = message_threshold
        self.time_interval_minutes = time_interval_minutes
        self.duration_hours = duration_hours

    async def on_submit(self, interaction: discord.Interaction):
        """
        当用户提交模态窗口时被调用。
        职责: 验证输入，构建视图元素，然后将所有数据传递给 Cog 中的工作流方法进行处理。
        """
        await self.bot.api_scheduler.submit(
            coro=interaction.response.defer(ephemeral=True, thinking=True), priority=1
        )

        try:
            # 数据验证
            title = self.title_input.value
            content = self.content_input.value

            # 准备视图和时间数据
            start_time_utc = datetime.now(ZoneInfo("UTC"))
            timezone = self.bot.config.get("timezone", "UTC")
            end_time = self.bot.time_utils.get_utc_end_time(
                self.duration_hours, timezone, start_time=start_time_utc
            )
            utc_aware_end_time = end_time.replace(tzinfo=ZoneInfo("UTC"))
            end_time_timestamp = int(utc_aware_end_time.timestamp())
            discord_timestamp = f"<t:{end_time_timestamp}:F> (<t:{end_time_timestamp}:R>)"

            # 使用 Builder 构建视图元素
            thread_content = AnnouncementEmbedBuilder.create_thread_content(
                title=title,
                content=content,
                discord_timestamp=discord_timestamp,
                author_id=interaction.user.id,
            )

            # 将所有数据和视图元素委托给 Cog
            await self.cog.create_announcement_workflow(
                interaction=interaction,
                title=title,
                content=content,
                end_time=end_time,
                thread_content=thread_content,
                discord_timestamp=discord_timestamp,
                start_time_utc=start_time_utc,
                enable_reposting=self.enable_reposting,
                message_threshold=self.message_threshold,
                time_interval_minutes=self.time_interval_minutes,
            )

        except Exception as e:
            logger.exception("在 Modal on_submit 期间发生意外错误")
            await self.bot.api_scheduler.submit(
                coro=interaction.followup.send(
                    f"处理表单时发生未知错误，请联系技术员。\n`{e}`", ephemeral=True
                ),
                priority=1,
            )
