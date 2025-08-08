import logging

import discord
from discord import app_commands
from discord.ext import commands

from StellariaPact.share.auth.MissingRole import MissingRole
from StellariaPact.share.StellariaPactBot import StellariaPactBot

from .logic.VotingLogic import VotingLogic

logger = logging.getLogger("stellaria_pact.voting")


class Voting(commands.Cog):
    """
    处理所有与投票相关的命令和交互。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.logic = VotingLogic(bot)

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
            logger.error(f"在 Voting Cog 中发生未处理的错误: {error}", exc_info=True)
            if not interaction.response.is_done():
                await self.bot.api_scheduler.submit(
                    coro=interaction.response.send_message(
                        "发生了一个未知错误，请联系技术员", ephemeral=True
                    ),
                    priority=1,
                )

    # @app_commands.command(name="启动投票", description="在当前帖子中启动投票")
    # @app_commands.rename(realtime="是否实时", anonymous="是否匿名")
    # @app_commands.describe(
    #     topic="投票的主题",
    #     realtime="是否实时显示投票结果 (默认: 否)",
    #     anonymous="是否匿名投票 (默认: 是)",
    # )
    # @RoleGuard.requireRoles("councilModerator", "executionAuditor")
    # async def start_vote(
    #     self,
    #     interaction: discord.Interaction,
    #     topic: str,
    #     realtime: bool = False,
    #     anonymous: bool = True,
    # ):
    #     """
    #     手动启动一个投票。
    #     """
    #     await self.bot.api_scheduler.submit(coro=safeDefer(interaction), priority=1)

    #     if not interaction.channel or not isinstance(interaction.channel, discord.Thread):
    #         await self.bot.api_scheduler.submit(
    #             coro=interaction.followup.send(
    #                 "此命令只能在帖子（Thread）内使用。", ephemeral=True
    #             ),
    #             priority=1,
    #         )
    #         return

    #     discussion_channel_id = self.bot.config.get("channels", {}).get("discussion")
    #     if not discussion_channel_id or interaction.channel.parent_id != int(
    #         discussion_channel_id
    #     ):
    #         await self.bot.api_scheduler.submit(
    #             coro=interaction.followup.send(
    #                 "此命令只能在指定的讨论区帖子内使用。", ephemeral=True
    #             ),
    #             priority=1,
    #         )
    #         return

    #     try:
    #         async with UnitOfWork(self.bot.db_handler) as uow:
    #             # 构建 UI
    #             view = VoteView(self.bot)
    #             embed = VoteEmbedBuilder.create_initial_vote_embed(
    #                 topic=topic,
    #                 author=interaction.user,
    #                 realtime=realtime,
    #                 anonymous=anonymous,
    #             )

    #             # 发送 API 请求
    #             message = await self.bot.api_scheduler.submit(
    #                 interaction.channel.send(embed=embed, view=view), priority=2
    #             )

    #             # 执行数据库操作
    #             qo = CreateVoteSessionQo(
    #                 thread_id=interaction.channel.id,
    #                 context_message_id=message.id,
    #                 realtime=realtime,
    #                 anonymous=anonymous,
    #             )
    #             await uow.voting.create_vote_session(qo)

    #         # 发送最终确认
    #         await self.bot.api_scheduler.submit(
    #             coro=interaction.followup.send(f"投票 '{topic}' 已成功启动！", ephemeral=True),
    #             priority=1,
    #         )
    #         logger.info(
    #             f"用户 {interaction.user.id} 在帖子 {interaction.channel.id} 中 "
    #             f"手动启动了投票 '{topic}'"
    #         )

    #     except Exception as e:
    #         logger.error(f"启动投票时发生命令特定错误: {e}", exc_info=True)
    #         raise e
