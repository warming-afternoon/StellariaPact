import logging
from typing import TYPE_CHECKING

import discord
from discord import ui

from StellariaPact.share.StellariaPactBot import StellariaPactBot

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

    duration_hours_input = ui.TextInput(
        label="公示持续小时数",
        placeholder="例如: 6 (代表公示6小时)",
        style=discord.TextStyle.short,
        required=True,
        default="6",
    )
    link_input = ui.TextInput(
        label="关联已有帖子链接 (可选)",
        placeholder="如果留空，将自动创建新帖子",
        style=discord.TextStyle.short,
        required=False,
    )

    def __init__(
        self,
        bot: StellariaPactBot,
        notification_cog: "Notification",
        enable_reposting: bool,
        message_threshold: int,
        time_interval_minutes: int,
        auto_execute: bool,
    ):
        super().__init__(timeout=1800)
        self.bot = bot
        self.cog = notification_cog
        self.enable_reposting = enable_reposting
        self.message_threshold = message_threshold
        self.time_interval_minutes = time_interval_minutes
        self.auto_execute = auto_execute

    async def on_submit(self, interaction: discord.Interaction):
        """
        当用户提交模态窗口时被调用。
        职责: 验证输入，构建视图元素，然后将所有数据传递给 Cog 中的工作流方法进行处理。
        """

        await self.bot.api_scheduler.submit(
            coro=interaction.response.defer(ephemeral=True, thinking=True), priority=1
        )
        try:
            # --- 数据验证 ---
            title = self.title_input.value
            content = self.content_input.value
            link = self.link_input.value or None  # 如果为空字符串则转为 None

            try:
                duration_hours = int(self.duration_hours_input.value)
                if not (4 <= duration_hours <= 168):
                    raise ValueError("公示持续小时数必须在 4-168 之间。")
            except (ValueError, TypeError):
                await interaction.followup.send(
                    "“公示持续小时数”必须是一个有效的整数。(4~168)", ephemeral=True
                )
                return

            await self.cog.create_announcement_workflow(
                interaction=interaction,
                title=title,
                content=content,
                duration_hours=duration_hours,
                link=link,
                auto_execute=self.auto_execute,
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
