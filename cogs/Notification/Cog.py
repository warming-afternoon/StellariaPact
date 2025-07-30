import discord
import logging
from discord import app_commands
from discord.ext import commands
from share.StellariaPactBot import StellariaPactBot
from cogs.Notification.views.AnnouncementModal import AnnouncementModal

logger = logging.getLogger('stellaria_pact.notification')

class Notification(commands.Cog):
    """
    处理所有与通知相关的命令，例如发布公示。
    """
    def __init__(self, bot: StellariaPactBot):
        self.bot = bot

    @app_commands.command(name="发布公示", description="通过表单发布一个新的社区公示")
    async def publish_announcement(self, interaction: discord.Interaction):
        """
        处理 /发布公示 命令, 弹出一个模态窗口来收集信息。
        """
        modal = AnnouncementModal(self.bot)
        await interaction.response.send_modal(modal)


async def setup(bot: StellariaPactBot):
    await bot.add_cog(Notification(bot))