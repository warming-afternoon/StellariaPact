import discord
import logging
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta

from share.StellariaPactBot import StellariaPactBot
from share.SafeDefer import safe_defer
from cogs.Notification.AnnouncementService import AnnouncementService
from cogs.Notification.qo.CreateAnnouncementQo import CreateAnnouncementQo

logger = logging.getLogger('stellaria_pact.notification')

class Notification(commands.Cog):
    """
    处理所有与通知相关的命令，例如发布公示。
    """
    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.announcement_service = AnnouncementService()
        self.discussion_channel_id = self.bot.config['channels']['discussion']
        self.broadcast_channel_ids = self.bot.config['channels']['broadcast']
        self.in_progress_tag_id = self.bot.config['tags']['announcement_in_progress']

    @app_commands.command(name="发布公示", description="发布一个新的社区公示")
    @app_commands.describe(
        title="公示的标题",
        content="公示的具体内容",
        duration_hours="公示持续的小时数 (例如 24, 48, 72)"
    )
    async def publish_announcement(self, interaction: discord.Interaction, title: str, content: str, duration_hours: int):
        """
        处理 /发布公示 命令
        """
        await safe_defer(interaction)

        try:
            # 1. 创建讨论帖并应用标签
            discussion_channel = self.bot.get_channel(self.discussion_channel_id)
            if not isinstance(discussion_channel, discord.ForumChannel):
                await interaction.followup.send("错误：配置的讨论区频道不是有效的论坛频道。", ephemeral=True)
                return

            target_tag = discord.utils.get(discussion_channel.available_tags, id=self.in_progress_tag_id)
            if not target_tag:
                await interaction.followup.send("错误：在论坛频道中找不到配置的“公示中”标签。", ephemeral=True)
                return

            thread_name = f"【公示】{title}"
            thread_content = f"**公示标题:** {title}\n\n**具体内容:**\n{content}\n\n*请在此帖内进行讨论。*"
            
            thread_creation_result = await discussion_channel.create_thread(
                name=thread_name,
                content=thread_content,
                applied_tags=[target_tag]
            )
            thread = thread_creation_result.thread

            # 2. 在数据库中创建记录
            end_time = datetime.utcnow() + timedelta(hours=duration_hours)
            
            qo = CreateAnnouncementQo(
                discussionThreadId=thread.id,
                announcerId=interaction.user.id,
                title=title,
                content=content,
                endTime=end_time
            )
            
            async with self.bot.db_handler.get_session() as session:
                announcement_dto = await self.announcement_service.create_announcement(session, qo)

            # 3. 转发到广播频道
            embed = discord.Embed(
                title=f"📢 新公示: {announcement_dto.title}",
                description=f"{announcement_dto.content}\n\n[点击此处参与讨论]({thread.jump_url})",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            embed.set_footer(text=f"公示发起人: {interaction.user.display_name}")
            embed.add_field(name="公示截止时间", value=f"<t:{int(announcement_dto.endTime.timestamp())}:F>")

            for channel_id in self.broadcast_channel_ids:
                channel = self.bot.get_channel(channel_id)
                if isinstance(channel, discord.TextChannel):
                    await self.bot.api_scheduler.submit(
                        coro=channel.send(embed=embed),
                        priority=5
                    )

            # 4. 成功回复
            await interaction.followup.send(f"✅ 公示 **{announcement_dto.title}** 已成功发布！讨论帖已在 {thread.mention} 创建。", ephemeral=True)

        except Exception as e:
            logger.exception("发布公示时发生错误")
            await interaction.followup.send(f"发布公示时发生未知错误，请联系管理员。\n`{e}`", ephemeral=True)


async def setup(bot: StellariaPactBot):
    await bot.add_cog(Notification(bot))