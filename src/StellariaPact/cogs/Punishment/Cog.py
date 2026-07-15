import logging

import discord
from discord import app_commands
from discord.ext import commands

from StellariaPact.repository.GlobalVotingRestrictionRepository import (
    GlobalVotingRestrictionAlreadyActiveError,
    GlobalVotingRestrictionNotFoundError,
)
from StellariaPact.share import StellariaPactBot, UnitOfWork
from StellariaPact.share.auth import RoleGuard
from StellariaPact.share.SafeDefer import safeDefer

from .logic.PunishmentLogic import PunishmentLogic
from .views.PunishmentEmbedBuilder import PunishmentEmbedBuilder
from .views.PunishmentHistoryModal import PunishmentHistoryModal
from .views.PunishmentModal import PunishmentModal
from .views.RemovePunishmentModal import RemovePunishmentModal

logger = logging.getLogger(__name__)


class PunishmentCog(commands.Cog):
    """
    处理所有与用户议事处罚（禁言、剥夺投票权）相关的交互。
    """

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.logic = PunishmentLogic(bot)

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

        self.remove_punishment_ctx = app_commands.ContextMenu(
            name="解除提案处罚",
            callback=self.remove_punishment_message,
            type=discord.AppCommandType.message,  # 消息右键
        )

        self.query_punishment_ctx = app_commands.ContextMenu(
            name="查询提案处罚记录",
            callback=self.query_punishment_message,
            type=discord.AppCommandType.message,
        )

    def cog_load(self) -> None:
        self.bot.tree.add_command(self.kick_proposal_ctx)
        self.bot.tree.add_command(self.remove_punishment_ctx)
        self.bot.tree.add_command(self.query_punishment_ctx)
        # self.bot.tree.add_command(self.manage_punishment_ctx)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(
            self.kick_proposal_ctx.name,
            type=self.kick_proposal_ctx.type,
        )
        self.bot.tree.remove_command(
            self.remove_punishment_ctx.name,
            type=self.remove_punishment_ctx.type,
        )
        self.bot.tree.remove_command(
            self.query_punishment_ctx.name,
            type=self.query_punishment_ctx.type,
        )
        # self.bot.tree.remove_command(
        #     self.manage_punishment_ctx.name,
        #     type=self.manage_punishment_ctx.type,
        # )

    @app_commands.command(
        name="永久剥夺投票资格",
        description="[管理组/议事督导] 永久剥夺用户在本机器人范围内的投票资格",
    )
    @app_commands.rename(target_user="用户", reason="处罚理由", evidence="处罚依据")
    @app_commands.describe(
        target_user="要永久剥夺投票资格的用户",
        reason="处罚理由",
        evidence="可选的处罚依据图片",
    )
    @RoleGuard.requireRoles("councilModerator", "stewards")
    async def permanently_restrict_voting(
        self,
        interaction: discord.Interaction,
        target_user: discord.Member,
        reason: str,
        evidence: discord.Attachment | None = None,
    ) -> None:
        """永久剥夺用户的机器人全局投票资格。"""
        if not await self._validate_global_command(interaction, target_user, reason):
            return
        if evidence and (
            evidence.content_type is None or not evidence.content_type.startswith("image/")
        ):
            await interaction.response.send_message("处罚依据只允许上传图片。", ephemeral=True)
            return

        await safeDefer(interaction, ephemeral=True)
        moderator = interaction.user
        guild = interaction.guild
        channel_id = interaction.channel_id
        if not isinstance(moderator, discord.Member) or guild is None or channel_id is None:
            await interaction.followup.send("此指令只能在服务器内使用。", ephemeral=True)
            return

        try:
            await self.logic.apply_global_voting_restriction(
                target_user_id=target_user.id,
                moderator_id=moderator.id,
                origin_guild_id=guild.id,
                origin_channel_id=channel_id,
                reason=reason.strip(),
                evidence_url=evidence.url if evidence else None,
                evidence_filename=evidence.filename if evidence else None,
            )
        except GlobalVotingRestrictionAlreadyActiveError:
            await interaction.followup.send(
                f"用户 {target_user.mention} 已被永久剥夺投票资格。",
                ephemeral=True,
            )
            return
        except Exception as exc:
            logger.error("创建全局投票资格限制失败: %s", exc, exc_info=True)
            await interaction.followup.send("处理请求时发生错误，请联系技术人员。", ephemeral=True)
            return

        embed = PunishmentEmbedBuilder.create_global_voting_restriction_embed(
            moderator=moderator,
            target_user=target_user,
            reason=reason.strip(),
            origin_guild_name=guild.name,
            evidence_url=evidence.url if evidence else None,
        )
        public_sent, dm_sent = await self._send_global_restriction_notifications(
            interaction, target_user, embed
        )
        await interaction.followup.send(
            self._build_delivery_summary(
                f"已永久剥夺 {target_user.mention} 的投票资格。",
                public_sent,
                dm_sent,
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="解除永久投票资格限制",
        description="[管理组/议事督导] 解除用户的机器人全局投票资格限制",
    )
    @app_commands.rename(target_user="用户", reason="解除理由")
    @app_commands.describe(target_user="要恢复投票资格的用户", reason="解除理由")
    @RoleGuard.requireRoles("councilModerator", "stewards")
    async def lift_permanent_voting_restriction(
        self,
        interaction: discord.Interaction,
        target_user: discord.Member,
        reason: str,
    ) -> None:
        """解除用户的机器人全局投票资格限制。"""
        if not await self._validate_global_command(interaction, target_user, reason):
            return

        await safeDefer(interaction, ephemeral=True)
        moderator = interaction.user
        guild = interaction.guild
        if not isinstance(moderator, discord.Member) or guild is None:
            await interaction.followup.send("此指令只能在服务器内使用。", ephemeral=True)
            return

        try:
            original_created_at = await self.logic.lift_global_voting_restriction(
                target_user_id=target_user.id,
                lifted_by_id=moderator.id,
                lift_reason=reason.strip(),
            )
        except GlobalVotingRestrictionNotFoundError:
            await interaction.followup.send(
                f"用户 {target_user.mention} 当前没有永久投票资格限制。",
                ephemeral=True,
            )
            return
        except Exception as exc:
            logger.error("解除全局投票资格限制失败: %s", exc, exc_info=True)
            await interaction.followup.send("处理请求时发生错误，请联系技术人员。", ephemeral=True)
            return

        embed = PunishmentEmbedBuilder.create_global_voting_restriction_lifted_embed(
            moderator=moderator,
            target_user=target_user,
            reason=reason.strip(),
            origin_guild_name=guild.name,
            original_created_at=original_created_at,
        )
        public_sent, dm_sent = await self._send_global_restriction_notifications(
            interaction, target_user, embed
        )
        await interaction.followup.send(
            self._build_delivery_summary(
                f"已恢复 {target_user.mention} 的投票资格。",
                public_sent,
                dm_sent,
            ),
            ephemeral=True,
        )

    async def _validate_global_command(
        self,
        interaction: discord.Interaction,
        target_user: discord.Member,
        reason: str,
    ) -> bool:
        if interaction.guild is None or interaction.channel_id is None:
            await interaction.response.send_message("此指令只能在服务器内使用。", ephemeral=True)
            return False
        if target_user.bot:
            await interaction.response.send_message("不能对机器人执行此操作。", ephemeral=True)
            return False
        if interaction.user.id == target_user.id:
            await interaction.response.send_message("不能对自己执行此操作。", ephemeral=True)
            return False
        if not reason.strip():
            await interaction.response.send_message("理由不能为空。", ephemeral=True)
            return False
        if len(reason) > 1000:
            await interaction.response.send_message("理由不能超过 1000 个字符。", ephemeral=True)
            return False
        return True

    async def _send_global_restriction_notifications(
        self,
        interaction: discord.Interaction,
        target_user: discord.Member,
        embed: discord.Embed,
    ) -> tuple[bool, bool]:
        public_sent = False
        dm_sent = False

        channel = interaction.channel
        if channel is not None:
            try:
                await self.bot.api_scheduler.submit(channel.send(embed=embed), priority=5)
                public_sent = True
            except Exception as exc:
                logger.warning("发送全局投票资格限制公示失败: %s", exc, exc_info=True)

        try:
            await self.bot.api_scheduler.submit(target_user.send(embed=embed), priority=5)
            dm_sent = True
        except Exception as exc:
            logger.warning("向用户 %s 发送处罚私信失败: %s", target_user.id, exc)

        return public_sent, dm_sent

    @staticmethod
    def _build_delivery_summary(
        result: str,
        public_sent: bool,
        dm_sent: bool,
    ) -> str:
        return (
            f"{result}\n"
            f"公开公示：{'成功' if public_sent else '失败'}；"
            f"用户私信：{'成功' if dm_sent else '失败'}。"
        )

    @RoleGuard.requireRoles("councilModerator", "stewards")
    async def remove_punishment_message(
        self, interaction: discord.Interaction, message: discord.Message
    ):
        """[议事督导/管理组] 解除该消息作者在当前帖子的处罚"""
        # 目标用户是消息的作者
        target_member = message.author

        if not await self._validate_context(interaction, target_member):
            return

        # 弹出 Modal，传入目标作者
        modal = RemovePunishmentModal(self.bot, target_member)
        await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), priority=1)

    @RoleGuard.requireRoles("councilModerator", "stewards")
    async def kick_proposal_message(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
    ):
        """[议事督导/管理组] 处罚发送该消息的用户"""
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

    @RoleGuard.requireRoles("councilModerator", "stewards")
    async def query_punishment_message(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
    ):
        """[议事督导/管理组] 查询消息作者在当前帖子中的处罚历史。"""
        thread = interaction.channel
        if not isinstance(thread, discord.Thread):
            await self.bot.api_scheduler.submit(
                interaction.response.send_message(
                    "此命令只能在提案帖子内使用。",
                    ephemeral=True,
                ),
                priority=1,
            )
            return

        async with UnitOfWork(self.bot.db_handler) as uow:
            total, records = await uow.punishment_record.get_summary(
                thread_id=thread.id,
                target_user_id=message.author.id,
            )
            modal = PunishmentHistoryModal(message.author, total, records)

        await self.bot.api_scheduler.submit(
            interaction.response.send_modal(modal),
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
