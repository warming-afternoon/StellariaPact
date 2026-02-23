from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import Interaction, app_commands
from discord.ext import commands

from StellariaPact.cogs.Intake.listeners.IntakeEventListener import IntakeEventListenerCog
from StellariaPact.cogs.Intake.views.IntakeReviewView import IntakeReviewView
from StellariaPact.cogs.Intake.views.IntakeSubmissionView import IntakeSubmissionView
from StellariaPact.share.auth.RoleGuard import RoleGuard

from .IntakeCloser import IntakeCloser
from .IntakeLogic import IntakeLogic

if TYPE_CHECKING:
    from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


class IntakeCog(commands.Cog):
    """处理所有与提案预审（Intake）相关的交互和命令"""

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.logic = IntakeLogic(bot)
        self.closer = IntakeCloser(self)  # 启动清理器
        # 在 bot 启动时注册持久化视图
        bot.add_view(IntakeSubmissionView())
        bot.add_view(IntakeReviewView(bot))

    def cog_unload(self):
        """当 Cog 被卸载时停止定时任务"""
        self.closer.stop()

    @app_commands.command(name="设置提交入口", description="[管理组]设置提案提交面板")
    @RoleGuard.requireRoles("stewards")
    async def setup_intake_button(self, interaction: Interaction):
        """
        发送一个带有“提交草案”按钮的消息，用户可以点击该按钮来开启提交流程。
        """
        if not interaction.channel or not isinstance(
            interaction.channel, (discord.TextChannel, discord.Thread)
        ):
            await interaction.response.send_message(
                "此命令只能在文本频道或论坛帖子中使用。", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="📝 议案预审核提交入口",
            description="请点击下方的按钮，并按照议案表格的格式填写内容。",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="表单包含以下字段",
            value=(
                "• **议案标题**: 简洁明了，不超过30字\n"
                "• **提案原因**: 说明提出此动议的原因\n"
                "• **议案动议**: 详细说明您的议案内容\n"
                "• **执行方案**: 说明如何落实此动议\n"
                "• **议案执行人**: 指定负责执行此议案的人员或部门"
            ),
            inline=False,
        )
        embed.add_field(
            name="审核流程",
            value=(
                "1. 提交后议案将在预审核论坛创建审核帖\n"
                "2. 管理员审核通过后发送到投票频道\n"
                "3. 需要获得 **20** 个支持才能进入讨论阶段"
            ),
            inline=False,
        )

        view = IntakeSubmissionView()
        await interaction.channel.send(embed=embed, view=view)
        await interaction.response.send_message("设置成功！", ephemeral=True)


async def setup(bot: StellariaPactBot):
    intake_cog = IntakeCog(bot)
    await bot.add_cog(intake_cog)
    await bot.add_cog(IntakeEventListenerCog(bot, intake_cog))
