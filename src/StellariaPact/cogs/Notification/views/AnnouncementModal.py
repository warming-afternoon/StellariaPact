import asyncio
import logging
from datetime import datetime

import discord
from discord import ui
from zoneinfo import ZoneInfo

from StellariaPact.cogs.Notification.AnnouncementService import AnnouncementService
from StellariaPact.cogs.Notification.qo.CreateAnnouncementQo import CreateAnnouncementQo
from StellariaPact.share.StellariaPactBot import StellariaPactBot

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

    duration_input = ui.TextInput(
        label="公示持续小时数",
        placeholder="请输入一个整数，例如 24, 48, 72",
        style=discord.TextStyle.short,
        required=True,
        max_length=3,
    )

    def __init__(self, bot: StellariaPactBot):
        super().__init__()
        self.bot = bot
        self.announcement_service = AnnouncementService()
        self.discussion_channel_id = self.bot.config["channels"]["discussion"]
        self.broadcast_channel_ids = self.bot.config["channels"]["broadcast"]
        self.in_progress_tag_id = self.bot.config["tags"]["announcement_in_progress"]

    async def on_submit(self, interaction: discord.Interaction):
        """
        当用户提交模态窗口时被调用。
        """
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            # 1. 数据验证
            title = self.title_input.value
            content = self.content_input.value
            try:
                duration_hours = int(self.duration_input.value)
                if duration_hours <= 0:
                    raise ValueError
            except ValueError:
                await interaction.followup.send(
                    "错误：公示持续小时数必须是一个正整数。", ephemeral=True
                )
                return

            # 2. 创建讨论帖并应用标签
            discussion_channel = self.bot.get_channel(self.discussion_channel_id)
            if not isinstance(discussion_channel, discord.ForumChannel):
                await interaction.followup.send(
                    "错误：配置的讨论区频道不是有效的论坛频道。", ephemeral=True
                )
                return

            target_tag = discord.utils.get(
                discussion_channel.available_tags, id=self.in_progress_tag_id
            )
            if not target_tag:
                await interaction.followup.send(
                    "错误：在论坛频道中找不到配置的“公示中”标签。", ephemeral=True
                )
                return

            # 3. 计算时间
            # 首先获取一个统一的、带时区的“现在”时间点，以确保所有计算基于同一基准
            start_time_utc = datetime.now(ZoneInfo("UTC"))

            timezone = self.bot.config.get("timezone", "UTC")
            end_time = self.bot.time_utils.get_utc_end_time(
                duration_hours, timezone, start_time=start_time_utc
            )

            # `end_time` 是一个 naive datetime，但其数值代表 UTC。
            # 在调用 .timestamp() 前必须使其成为 aware 对象。
            utc_aware_end_time = end_time.replace(tzinfo=ZoneInfo("UTC"))
            discord_timestamp = f"<t:{int(utc_aware_end_time.timestamp())}:F>"

            # 4. 创建讨论帖并应用标签
            thread_name = f"【公示】{title}"
            thread_content = (
                f"{content}\n\n**公示截止时间:** {discord_timestamp}\n\n*请在此帖内进行讨论*"
                + f"\n公示发起人: {interaction.user.mention}"
            )

            thread_creation_result = await discussion_channel.create_thread(
                name=thread_name, content=thread_content, applied_tags=[target_tag]
            )
            thread = thread_creation_result.thread

            # --- 数据库创建和广播 ---
            tasks = []

            # 任务1: 在数据库中创建记录
            qo = CreateAnnouncementQo(
                discussionThreadId=thread.id,
                announcerId=interaction.user.id,
                title=title,
                content=content,
                endTime=end_time,
            )

            async def create_in_db():
                async with self.bot.db_handler.get_session() as session:
                    return await self.announcement_service.create_announcement(session, qo)

            db_creation_task = asyncio.create_task(create_in_db())
            tasks.append(db_creation_task)

            # 任务2: 转发到广播频道
            embed = discord.Embed(
                title=f"📢 新公示: {title}",
                description=f"{content}\n\n[点击此处参与讨论]({thread.jump_url})",
                color=discord.Color.blue(),
                timestamp=start_time_utc,
            )
            embed.set_footer(
                text=f"公示发起人: {interaction.user.display_name}",
                icon_url=interaction.user.display_avatar.url,
            )
            embed.add_field(name="公示截止时间", value=discord_timestamp, inline=False)

            for channel_id in self.broadcast_channel_ids:
                channel = self.bot.get_channel(channel_id)
                if isinstance(channel, discord.TextChannel):
                    tasks.append(
                        self.bot.api_scheduler.submit(coro=channel.send(embed=embed), priority=5)
                    )

            # 并行执行所有任务
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 检查结果并发送最终反馈
            failed_tasks_details = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    task_name = (
                        "数据库创建"
                        if i == 0
                        else f"广播到频道 {self.broadcast_channel_ids[i - 1]}"
                    )
                    user_friendly_error = ""
                    if isinstance(result, discord.Forbidden):
                        user_friendly_error = "机器人缺少发送消息的权限。"
                    else:
                        user_friendly_error = f"发生未知错误: `{type(result).__name__}`"

                    failed_tasks_details.append(f"- {task_name}失败: {user_friendly_error}")
                    logger.error(f"发布公示时，任务 {task_name} 失败", exc_info=result)

            if not failed_tasks_details:
                await interaction.followup.send(
                    f"✅ 公示 **{title}** 已成功发布！\n讨论帖已在 {thread.mention} 创建。",
                    ephemeral=True,
                )
            else:
                error_summary = "\n".join(failed_tasks_details)
                await interaction.followup.send(
                    f"公示 **{title}** 发布过程中出现问题：\n{error_summary}\n"
                    f"讨论帖已在 {thread.mention} 创建，但部分操作未成功，请联系技术员。",
                    ephemeral=True,
                )

        except discord.Forbidden:
            logger.exception("通过 Modal 发布公示时发生权限错误")
            await interaction.followup.send(
                "发布公示时发生权限错误：机器人可能缺少创建帖子或应用标签的权限。请检查频道设置。",
                ephemeral=True,
            )
        except Exception as e:
            logger.exception("通过 Modal 发布公示时发生错误")
            await interaction.followup.send(
                f"发布公示时发生未知错误，请联系技术员。\n`{e}`", ephemeral=True
            )
