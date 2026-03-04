import logging

import discord
from discord import app_commands
from discord.ext import commands

from StellariaPact.share import StellariaPactBot
from StellariaPact.share.auth import RoleGuard

from .views.PunishmentModal import PunishmentModal

logger = logging.getLogger(__name__)

class PunishmentCog(commands.Cog):
    """
    处理所有与用户议事处罚（禁言、剥夺投票权）相关的交互。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot

        # 消息右键菜单：踢出提案 (针对特定发言)
        self.kick_proposal_ctx = app_commands.ContextMenu(
            name="踢出提案",
            callback=self.kick_proposal_message,
            type=discord.AppCommandType.message,
        )
        # # 用户右键菜单：管理处罚 (针对特定用户)
        # self.manage_punishment_ctx = app_commands.ContextMenu(
        #     name="管理处罚",
        #     callback=self.manage_punishment_user,
        #     type=discord.AppCommandType.user,
        # )

    def cog_load(self) -> None:
        self.bot.tree.add_command(self.kick_proposal_ctx)
        # self.bot.tree.add_command(self.manage_punishment_ctx)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(
            self.kick_proposal_ctx.name,
            type=self.kick_proposal_ctx.type,
        )
        # self.bot.tree.remove_command(
        #     self.manage_punishment_ctx.name,
        #     type=self.manage_punishment_ctx.type,
        # )

    @RoleGuard.requireRoles("councilModerator")
    async def kick_proposal_message(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
    ):
        """[议事督导] 消息右键：将发送该消息的用户处罚"""
        if not await self._validate_context(interaction, message.author):
            return

        # 对于新触发的处罚，不查询历史，直接弹出默认表单
        modal = PunishmentModal(
            bot=self.bot,
            target_user=message.author,
            target_message=message,
        )
        await self.bot.api_scheduler.submit(
            coro=interaction.response.send_modal(modal),
            priority=1,
        )

    # @RoleGuard.requireRoles("councilModerator")
    # async def manage_punishment_user(
    #     self,
    #     interaction: discord.Interaction,
    #     member: discord.Member,
    # ):
    #     """[议事督导] 用户右键：管理该用户在当前帖子的处罚状态"""
    #     if not await self._validate_context(interaction, member):
    #         return

    #     activity = None
    #     thread = interaction.channel
    #     if not isinstance(thread, discord.Thread):
    #         return

    #     # 查询该用户在当前帖子是否已有记录
    #     async with UnitOfWork(self.bot.db_handler) as uow:
    #         activity = await uow.user_activity.get_user_activity(  # type: ignore
    #             member.id,
    #             thread.id,
    #         )

    #     # 将已有的记录传入 Modal，实现数据预填
    #     modal = PunishmentModal(
    #         bot=self.bot,
    #         target_user=member,
    #         target_message=None,
    #         existing_activity=activity,
    #     )
    #     await self.bot.api_scheduler.submit(
    #         coro=interaction.response.send_modal(modal),
    #         priority=1,
    #     )

    async def _validate_context(
        self,
        interaction: discord.Interaction,
        target_user: discord.User | discord.Member,
    ) -> bool:
        """验证命令是否在正确的上下文中使用"""
        if not isinstance(interaction.channel, discord.Thread):
            await self.bot.api_scheduler.submit(
                interaction.response.send_message(
                    "此命令只能在提案帖子内使用。",
                    ephemeral=True,
                ),
                1,
            )
            return False

        if target_user.bot:
            await self.bot.api_scheduler.submit(
                interaction.response.send_message(
                    "不能对机器人执行此操作。",
                    ephemeral=True,
                ),
                1,
            )
            return False

        if interaction.user.id == target_user.id:
            await self.bot.api_scheduler.submit(
                interaction.response.send_message(
                    "不能对自己执行此操作。",
                    ephemeral=True,
                ),
                1,
            )
            return False

        return True
