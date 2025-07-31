import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from StellariaPact.cogs.Voting.views.VoteView import VoteView
from StellariaPact.cogs.Voting.VotingService import VotingService
from StellariaPact.share.auth.MissingRole import MissingRole
from StellariaPact.share.auth.RoleGuard import RoleGuard
from StellariaPact.share.SafeDefer import safeDefer
from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger("stellaria_pact.voting")


class Voting(commands.Cog):
    """
    处理所有与投票相关的命令和交互。
    """

    def __init__(self, bot: StellariaPactBot, voting_service: VotingService):
        self.bot = bot
        self.voting_service = voting_service

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
                    coro=interaction.response.send_message(
                        str(original_error), ephemeral=True
                    ),
                    priority=1,
                )
        else:
            logger.error(f"在 Voting Cog 中发生未处理的错误: {error}", exc_info=True)
            if not interaction.response.is_done():
                await self.bot.api_scheduler.submit(
                    coro=interaction.response.send_message(
                        "发生了一个未知错误，请联系管理员。", ephemeral=True
                    ),
                    priority=1,
                )

    @app_commands.command(name="启动投票", description="在当前帖子中启动投票")
    @app_commands.describe(topic="投票的主题")
    @RoleGuard.requireRoles("councilModerator", "executionAuditor")
    async def start_vote(self, interaction: discord.Interaction, topic: str):
        """
        手动启动一个投票。
        """
        await self.bot.api_scheduler.submit(safeDefer(interaction), priority=1)

        if not interaction.channel or not isinstance(
            interaction.channel, discord.Thread
        ):
            await self.bot.api_scheduler.submit(
                interaction.followup.send("此命令只能在帖子（Thread）内使用。", ephemeral=True),
                priority=1,
            )
            return

        # 检查是否在指定的讨论区
        discussion_channel_id = self.bot.config.get("channels", {}).get("discussion")
        if not discussion_channel_id or interaction.channel.parent_id != int(
            discussion_channel_id
        ):
            await self.bot.api_scheduler.submit(
                interaction.followup.send(
                    "此命令只能在指定的讨论区帖子内使用。", ephemeral=True
                ),
                priority=1,
            )
            return

        try:
            async with self.bot.db_handler.get_session() as session:
                await self.voting_service.create_vote_session(
                    session, interaction.channel.id
                )

            view = VoteView(self.bot, self.voting_service)
            embed = discord.Embed(
                title=f"议题：{topic}",
                description=f"由 {interaction.user.mention} 发起的投票已开始！请点击下方按钮参与。",
                color=discord.Color.blue(),
            )
            embed.set_footer(text="投票资格：在本帖内有效发言数 ≥ 3")

            await self.bot.api_scheduler.submit(
                interaction.channel.send(embed=embed, view=view), priority=2
            )

            await self.bot.api_scheduler.submit(
                interaction.followup.send(f"投票 '{topic}' 已成功启动！", ephemeral=True),
                priority=1,
            )
            logger.info(
                f"用户 {interaction.user.id} 在帖子 {interaction.channel.id} 中手动启动了投票 '{topic}'"
            )

        except Exception as e:
            # 错误将由 cog_app_command_error 捕获和处理
            logger.error(f"启动投票时发生命令特定错误: {e}", exc_info=True)
            # 抛出异常以确保它被全局错误处理器捕获
            raise e




async def setup(bot: StellariaPactBot):
    """
    设置并加载 Voting 模块的所有相关 Cogs。
    """
    from .listeners.MessageListener import MessageListener
    from .listeners.ThreadListener import ThreadListener
    from .tasks.VoteCloser import VoteCloser

    # 创建共享的 Service 实例
    voting_service = VotingService()

    # 创建所有 Cogs 并注入依赖
    cogs_to_load = [
        Voting(bot, voting_service),
        ThreadListener(bot, voting_service),
        MessageListener(bot, voting_service),
        VoteCloser(bot, voting_service)
    ]

    # 3. 使用 asyncio.gather 并行加载所有 Cogs
    await asyncio.gather(*[bot.add_cog(cog) for cog in cogs_to_load])

    logger.info(f"成功为 Voting 模块加载了 {len(cogs_to_load)} 个 Cogs。")
