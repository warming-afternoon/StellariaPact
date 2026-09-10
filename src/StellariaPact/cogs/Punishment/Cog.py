import copy
import logging
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.app_commands.errors import CommandLimitReached
from discord.ext import commands

from StellariaPact.cogs.StructuredSpeech.StructuredSpeechMessageTargetResolver import (
    StructuredSpeechMessageTargetResolver,
)
from StellariaPact.cogs.StructuredSpeech.StructuredSpeechUserError import (
    StructuredSpeechUserError,
)
from StellariaPact.qo.structured_speech import ResolveStructuredSpeechReferenceQo
from StellariaPact.repository.GlobalProposalPunishmentAlreadyActiveError import (
    GlobalProposalPunishmentAlreadyActiveError,
)
from StellariaPact.repository.GlobalProposalPunishmentNotFoundError import (
    GlobalProposalPunishmentNotFoundError,
)
from StellariaPact.share import StellariaPactBot, UnitOfWork
from StellariaPact.share.auth import RoleGuard
from StellariaPact.share.enums import PunishmentType
from StellariaPact.share.MessageForwardService import MessageForwardError
from StellariaPact.share.SafeDefer import safeDefer

from .logic.PunishmentLogic import PunishmentLogic
from .logic.PunishmentPublicityService import PunishmentPublicityService
from .qo.PublishPunishmentQo import PublishPunishmentQo
from .qo.ResolvePublicityChannelQo import ResolvePublicityChannelQo
from .views.GlobalProposalPunishmentHistoryModal import (
    GlobalProposalPunishmentHistoryModal,
)
from .views.PunishmentEmbedBuilder import PunishmentEmbedBuilder
from .views.PunishmentHistoryModal import PunishmentHistoryModal
from .views.PunishmentModal import PunishmentModal
from .views.RemovePunishmentModal import RemovePunishmentModal

logger = logging.getLogger(__name__)


class PunishmentCog(
    commands.GroupCog,
    group_name="提案处罚",
    group_description="议事处罚与投票资格管理",
):
    """
    处理所有与用户议事处罚（禁言、剥夺投票权）相关的交互。
    """

    _PERMANENT_CATEGORY_LABELS = {
        PunishmentType.PERMANENT_VOTING: "投票资格",
        PunishmentType.PERMANENT_OBJECTION_CREATION: "异议创建与附议",
    }

    # 快速处罚使用固定理由和禁言时长。
    _QUICK_PUNISH_OFF_TOPIC_REASON = "请不要歪楼滑坡"
    _QUICK_PUNISH_OFF_TOPIC_MUTE_MINUTES = 5

    def __init__(self, bot: StellariaPactBot):
        self.bot = bot
        self.logic = PunishmentLogic(bot)
        self.publicity_service = PunishmentPublicityService(bot)
        self.message_target_resolver = StructuredSpeechMessageTargetResolver(bot)

        # 消息右键菜单：踢出提案 (针对特定发言)
        self.kick_proposal_ctx = app_commands.ContextMenu(
            name="踢出提案",
            callback=self.kick_proposal_message,
            type=discord.AppCommandType.message,
        )
        # 注册无需填写表单的歪楼滑坡处罚入口。
        self.quick_punish_off_topic_ctx = app_commands.ContextMenu(
            name="快速处罚-歪楼滑坡",
            callback=self.quick_punish_off_topic_message,
            type=discord.AppCommandType.message,
        )
        # # 用户右键菜单：管理处罚 (针对特定用户)
        # self.manage_punishment_ctx = app_commands.ContextMenu(
        #     name="管理处罚",
        #     callback=self.manage_punishment_user,
        #     type=discord.AppCommandType.user,
        # )

        self.remove_punishment_ctx = app_commands.ContextMenu(
            name="解除提案内处罚",
            callback=self.remove_punishment_message,
            type=discord.AppCommandType.message,  # 消息右键
        )

        self.query_punishment_ctx = app_commands.ContextMenu(
            name="查询提案内处罚记录",
            callback=self.query_punishment_message,
            type=discord.AppCommandType.message,
        )

        self.query_global_proposal_punishment_ctx = app_commands.ContextMenu(
            name="查看全局提案处罚",
            callback=self.query_global_proposal_punishment_user,
            type=discord.AppCommandType.user,
        )

    def cog_load(self) -> None:
        """注册处罚右键菜单，并隔离菜单超限导致的加载失败。"""
        # 本模块占四个消息菜单，结构化发言回复占剩余一个；用户菜单单独计数。
        self._add_ctx_menus_safe(
            self.kick_proposal_ctx,
            self.remove_punishment_ctx,
            self.query_punishment_ctx,
            self.query_global_proposal_punishment_ctx,
            self.quick_punish_off_topic_ctx,
        )
        # self.bot.tree.add_command(self.manage_punishment_ctx)

    def _add_ctx_menus_safe(self, *menus: app_commands.ContextMenu) -> None:
        """逐个注册右键菜单；命中 CommandLimitReached 时记录并跳过。"""
        # 逐项注册，避免单个菜单超限影响其余命令加载。
        for menu in menus:
            try:
                self.bot.tree.add_command(menu)
            except CommandLimitReached:
                logger.warning(
                    "右键菜单 %s 因超出 Discord 全局上限（5 个/类型）未注册，已跳过",
                    menu.name,
                )

    async def cog_unload(self) -> None:
        """移除本模块注册的右键菜单。"""
        # 未成功注册的菜单无需额外清理。
        for menu in (
            self.kick_proposal_ctx,
            self.remove_punishment_ctx,
            self.query_punishment_ctx,
            self.query_global_proposal_punishment_ctx,
            self.quick_punish_off_topic_ctx,
        ):
            try:
                self.bot.tree.remove_command(menu.name, type=menu.type)
            except Exception:
                logger.debug("卸载右键菜单 %s 失败（可能未注册）", menu.name)
        # self.bot.tree.remove_command(
        #     self.manage_punishment_ctx.name,
        #     type=self.manage_punishment_ctx.type,
        # )

    @app_commands.command(
        name="永久剥夺权限",
        description="[管理组/议事督导] 按分类永久剥夺用户的提案权限",
    )
    @app_commands.rename(
        target_user="用户",
        category="分类",
        reason="处罚理由",
        evidence="处罚依据",
    )
    @app_commands.describe(
        target_user="要永久剥夺权限的用户",
        category="要剥夺的权限分类",
        reason="处罚理由",
        evidence="可选的处罚依据图片",
    )
    @app_commands.choices(
        category=[
            app_commands.Choice(name="投票资格", value=PunishmentType.PERMANENT_VOTING.value),
            app_commands.Choice(
                name="异议创建与附议",
                value=PunishmentType.PERMANENT_OBJECTION_CREATION.value,
            ),
        ]
    )
    @RoleGuard.requireRoles("councilModerator", "stewards")
    async def permanently_restrict_voting(
        self,
        interaction: discord.Interaction,
        target_user: discord.Member,
        category: app_commands.Choice[str],
        reason: str,
        evidence: discord.Attachment | None = None,
    ) -> None:
        """按分类永久剥夺用户的机器人全局提案权限。"""
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

        punishment_type = PunishmentType(category.value)
        category_label = self._PERMANENT_CATEGORY_LABELS[punishment_type]

        try:
            punishment_id = await self.logic.apply_permanent_restriction(
                punishment_type=punishment_type,
                target_user_id=target_user.id,
                moderator_id=moderator.id,
                origin_guild_id=guild.id,
                origin_channel_id=channel_id,
                reason=reason.strip(),
                evidence_url=evidence.url if evidence else None,
                evidence_filename=evidence.filename if evidence else None,
                moderator_name=moderator.name,
                moderator_display_name=moderator.display_name,
            )
        except GlobalProposalPunishmentAlreadyActiveError:
            await interaction.followup.send(
                f"用户 {target_user.mention} 已存在永久{category_label}限制。",
                ephemeral=True,
            )
            return
        except Exception as exc:
            logger.error("创建永久%s限制失败: %s", category_label, exc, exc_info=True)
            await interaction.followup.send("处理请求时发生错误，请联系技术人员。", ephemeral=True)
            return

        embed = PunishmentEmbedBuilder.create_permanent_restriction_embed(
            moderator=moderator,
            target_user=target_user,
            reason=reason.strip(),
            origin_guild_name=guild.name,
            punishment_type=punishment_type,
            evidence_url=evidence.url if evidence else None,
        )
        (
            public_sent,
            dm_sent,
            public_message_id,
        ) = await self._send_global_restriction_notifications(interaction, target_user, embed)
        if public_message_id is not None:
            await self._try_set_punishment_message_id(
                punishment_id,
                public_message_id,
            )
        await interaction.followup.send(
            self._build_delivery_summary(
                f"已永久剥夺 {target_user.mention} 的{category_label}。",
                public_sent,
                dm_sent,
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="解除永久权限限制",
        description="[管理组/议事督导] 按分类解除用户的永久提案权限限制",
    )
    @app_commands.rename(target_user="用户", category="分类", reason="解除理由")
    @app_commands.describe(
        target_user="要恢复权限的用户",
        category="要解除的权限限制分类",
        reason="解除理由",
    )
    @app_commands.choices(
        category=[
            app_commands.Choice(name="投票资格", value=PunishmentType.PERMANENT_VOTING.value),
            app_commands.Choice(
                name="异议创建与附议",
                value=PunishmentType.PERMANENT_OBJECTION_CREATION.value,
            ),
        ]
    )
    @RoleGuard.requireRoles("councilModerator", "stewards")
    async def lift_permanent_voting_restriction(
        self,
        interaction: discord.Interaction,
        target_user: discord.Member,
        category: app_commands.Choice[str],
        reason: str,
    ) -> None:
        """按分类解除用户的机器人全局提案权限限制。"""
        if not await self._validate_global_command(interaction, target_user, reason):
            return

        await safeDefer(interaction, ephemeral=True)
        moderator = interaction.user
        guild = interaction.guild
        if not isinstance(moderator, discord.Member) or guild is None:
            await interaction.followup.send("此指令只能在服务器内使用。", ephemeral=True)
            return

        punishment_type = PunishmentType(category.value)
        category_label = self._PERMANENT_CATEGORY_LABELS[punishment_type]

        try:
            punishment_id, original_created_at = await self.logic.lift_permanent_restriction(
                punishment_type=punishment_type,
                target_user_id=target_user.id,
                lifted_by_id=moderator.id,
                lift_reason=reason.strip(),
                moderator_name=moderator.name,
                moderator_display_name=moderator.display_name,
                guild_id=guild.id,
                channel_id=interaction.channel_id,
            )
        except GlobalProposalPunishmentNotFoundError:
            await interaction.followup.send(
                f"用户 {target_user.mention} 当前没有永久{category_label}限制。",
                ephemeral=True,
            )
            return
        except Exception as exc:
            logger.error("解除永久%s限制失败: %s", category_label, exc, exc_info=True)
            await interaction.followup.send("处理请求时发生错误，请联系技术人员。", ephemeral=True)
            return

        embed = PunishmentEmbedBuilder.create_permanent_restriction_lifted_embed(
            moderator=moderator,
            target_user=target_user,
            reason=reason.strip(),
            origin_guild_name=guild.name,
            original_created_at=original_created_at,
            punishment_type=punishment_type,
        )
        (
            public_sent,
            dm_sent,
            public_message_id,
        ) = await self._send_global_restriction_notifications(interaction, target_user, embed)
        if public_message_id is not None and interaction.channel_id is not None:
            await self._try_set_resolution_message(
                punishment_id,
                guild_id=guild.id,
                channel_id=interaction.channel_id,
                message_id=public_message_id,
            )
        await interaction.followup.send(
            self._build_delivery_summary(
                f"已恢复 {target_user.mention} 的{category_label}。",
                public_sent,
                dm_sent,
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="提案违规处罚",
        description="[管理组/议事督导/执行监理] 限时禁止用户参与提案活动",
    )
    @app_commands.rename(
        target_user="用户",
        days="天数",
        reason="处罚理由",
        evidence="处罚依据",
    )
    @app_commands.describe(
        target_user="要处罚的用户",
        days="处罚天数，必须为 1 至 30 天",
        reason="处罚理由",
        evidence="可选的处罚依据图片",
    )
    @RoleGuard.requireRoles("councilModerator", "executionAuditor", "stewards")
    async def punish_proposal_violation(
        self,
        interaction: discord.Interaction,
        target_user: discord.Member,
        days: app_commands.Range[int, 1, 30],
        reason: str,
        evidence: discord.Attachment | None = None,
    ) -> None:
        """限时禁止用户参与本机器人范围内的提案活动。"""
        if not await self._validate_global_command(interaction, target_user, reason):
            return
        if not 1 <= days <= 30:
            await interaction.response.send_message(
                "处罚天数必须在 1 至 30 天之间。", ephemeral=True
            )
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
            punishment_id, expires_at = await self.logic.apply_proposal_violation_punishment(
                target_user_id=target_user.id,
                moderator_id=moderator.id,
                origin_guild_id=guild.id,
                origin_channel_id=channel_id,
                days=days,
                reason=reason.strip(),
                evidence_url=evidence.url if evidence else None,
                evidence_filename=evidence.filename if evidence else None,
                moderator_name=moderator.name,
                moderator_display_name=moderator.display_name,
            )
        except GlobalProposalPunishmentAlreadyActiveError:
            await interaction.followup.send(
                f"用户 {target_user.mention} 已有正在生效的提案违规处罚，需解除后重新处罚。",
                ephemeral=True,
            )
            return
        except Exception as exc:
            logger.error("创建全局提案违规处罚失败: %s", exc, exc_info=True)
            await interaction.followup.send("处理请求时发生错误，请联系技术人员。", ephemeral=True)
            return

        self.bot.dispatch("proposal_violation_punishment_updated", target_user.id, expires_at)
        embed = PunishmentEmbedBuilder.create_proposal_violation_embed(
            moderator=moderator,
            target_user=target_user,
            reason=reason.strip(),
            origin_guild_name=guild.name,
            days=days,
            expires_at=expires_at,
            evidence_url=evidence.url if evidence else None,
        )
        (
            public_sent,
            dm_sent,
            public_message_id,
        ) = await self._send_global_restriction_notifications(interaction, target_user, embed)
        if public_message_id is not None:
            await self._try_set_punishment_message_id(
                punishment_id,
                public_message_id,
            )
        await interaction.followup.send(
            self._build_delivery_summary(
                f"已对 {target_user.mention} 执行 {days} 天提案违规处罚。",
                public_sent,
                dm_sent,
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="解除提案违规处罚",
        description="[管理组/议事督导/执行监理] 提前解除用户的提案违规处罚",
    )
    @app_commands.rename(target_user="用户", reason="解除理由")
    @app_commands.describe(target_user="要解除处罚的用户", reason="解除理由")
    @RoleGuard.requireRoles("councilModerator", "executionAuditor", "stewards")
    async def lift_proposal_violation(
        self,
        interaction: discord.Interaction,
        target_user: discord.Member,
        reason: str,
    ) -> None:
        if not await self._validate_global_command(interaction, target_user, reason):
            return

        await safeDefer(interaction, ephemeral=True)
        moderator = interaction.user
        guild = interaction.guild
        if not isinstance(moderator, discord.Member) or guild is None:
            await interaction.followup.send("此指令只能在服务器内使用。", ephemeral=True)
            return

        try:
            (
                punishment_id,
                created_at,
                expires_at,
            ) = await self.logic.lift_proposal_violation_punishment(
                target_user_id=target_user.id,
                lifted_by_id=moderator.id,
                lift_reason=reason.strip(),
                moderator_name=moderator.name,
                moderator_display_name=moderator.display_name,
                guild_id=guild.id,
                channel_id=interaction.channel_id,
            )
        except GlobalProposalPunishmentNotFoundError:
            await interaction.followup.send(
                f"用户 {target_user.mention} 当前没有有效的提案违规处罚。",
                ephemeral=True,
            )
            return
        except Exception as exc:
            logger.error("解除全局提案违规处罚失败: %s", exc, exc_info=True)
            await interaction.followup.send("处理请求时发生错误，请联系技术人员。", ephemeral=True)
            return

        self.bot.dispatch("proposal_violation_punishment_updated", target_user.id, None)
        embed = PunishmentEmbedBuilder.create_proposal_violation_lifted_embed(
            moderator=moderator,
            target_user=target_user,
            reason=reason.strip(),
            origin_guild_name=guild.name,
            original_created_at=created_at,
            original_expires_at=expires_at,
        )
        (
            public_sent,
            dm_sent,
            public_message_id,
        ) = await self._send_global_restriction_notifications(interaction, target_user, embed)
        if public_message_id is not None and interaction.channel_id is not None:
            await self._try_set_resolution_message(
                punishment_id,
                guild_id=guild.id,
                channel_id=interaction.channel_id,
                message_id=public_message_id,
            )
        await interaction.followup.send(
            self._build_delivery_summary(
                f"已提前解除 {target_user.mention} 的提案违规处罚。",
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
    ) -> tuple[bool, bool, int | None]:
        public_sent = False
        dm_sent = False
        public_message_id = None

        channel = interaction.channel
        if channel is not None:
            try:
                public_message = await self.bot.api_scheduler.submit(
                    channel.send(embed=embed),
                    priority=5,
                )
                public_sent = True
                public_message_id = getattr(public_message, "id", None)
            except Exception as exc:
                logger.warning("发送全局提案处罚公示失败: %s", exc, exc_info=True)

        dm_embed = copy.deepcopy(embed)
        guild_id = getattr(interaction, "guild_id", None)
        if guild_id is None:
            guild_id = getattr(getattr(interaction, "guild", None), "id", None)
        channel_id = getattr(interaction, "channel_id", None)
        if channel_id is None:
            channel_id = getattr(channel, "id", None)
        if guild_id is not None and channel_id is not None:
            if public_message_id is not None:
                source_url = (
                    f"https://discord.com/channels/{guild_id}/{channel_id}/{public_message_id}"
                )
                source_value = f"[查看公开公示]({source_url})"
            else:
                source_url = f"https://discord.com/channels/{guild_id}/{channel_id}"
                source_value = f"[查看来源频道]({source_url})"
            dm_embed.add_field(name="操作来源", value=source_value, inline=False)

        try:
            await self.bot.api_scheduler.submit(target_user.send(embed=dm_embed), priority=5)
            dm_sent = True
        except Exception as exc:
            logger.warning("向用户 %s 发送处罚私信失败: %s", target_user.id, exc)

        return public_sent, dm_sent, public_message_id

    async def _try_set_punishment_message_id(
        self,
        punishment_id: int,
        message_id: int,
    ) -> None:
        """尽力保存处罚公示消息 ID，不影响已完成的处罚和公示。"""
        try:
            await self.logic.set_punishment_message_id(punishment_id, message_id)
        except Exception as exc:
            logger.error(
                "保存全局处罚 %s 的公示消息 ID 失败: %s",
                punishment_id,
                exc,
                exc_info=True,
            )

    async def _try_set_resolution_message(
        self,
        punishment_id: int,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int,
    ) -> None:
        """尽力保存解除公示位置，不影响已完成的解除和公示。"""
        try:
            await self.logic.set_resolution_message(
                punishment_id,
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=message_id,
            )
        except Exception as exc:
            logger.error(
                "保存全局处罚 %s 的解除公示位置失败: %s",
                punishment_id,
                exc,
                exc_info=True,
            )

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
        # Webhook 结构化消息需要先还原为原提交用户。
        target_member = await self._resolve_message_target(interaction, message)
        if target_member is None:
            return

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
        # Webhook 结构化消息需要先还原为原提交用户。
        target_user = await self._resolve_message_target(interaction, message)
        if target_user is None:
            return
        if not await self._validate_context(interaction, target_user):
            return

        # 对于新触发的处罚，不查询历史，直接弹出默认表单
        modal = PunishmentModal(
            bot=self.bot,
            target_user=target_user,
            target_message=message,
        )
        await self.bot.api_scheduler.submit(
            coro=interaction.response.send_modal(modal),
            priority=1,
        )

    @RoleGuard.requireRoles("councilModerator", "stewards")
    async def quick_punish_off_topic_message(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
    ) -> None:
        """对选中消息的真实作者执行歪楼滑坡预设处罚并发布公示。"""
        # 解析结构化消息的原发言者，并校验处罚上下文。
        target_user = await self._resolve_message_target(interaction, message)
        if target_user is None:
            return
        if not await self._validate_context(interaction, target_user):
            return

        # 提前确认交互，为处罚写入和公示发送留出处理时间。
        await safeDefer(interaction, ephemeral=True)

        thread = interaction.channel
        moderator = interaction.user
        assert isinstance(thread, discord.Thread) and isinstance(moderator, discord.Member)

        mute_end_time = datetime.now(timezone.utc) + timedelta(
            minutes=self._QUICK_PUNISH_OFF_TOPIC_MUTE_MINUTES
        )

        # 通过业务层事务写入处罚，控制器只接收结果数据。
        result = await self.logic.apply_thread_punishment(
            guild_id=thread.guild.id,
            thread_id=thread.id,
            target_user_id=target_user.id,
            moderator_id=moderator.id,
            reason=self._QUICK_PUNISH_OFF_TOPIC_REASON,
            source_message_url=message.jump_url,
            voting_allowed=True,
            mute_end_time=mute_end_time,
        )

        # 同步内存禁言缓存（voting_allowed=True 不会产生需要刷新的投票面板）
        self.bot.dispatch(
            "thread_mute_updated",
            thread.id,
            target_user.id,
            mute_end_time,
        )
        for vote_details in result.vote_details_to_update:
            self.bot.dispatch("vote_details_updated", vote_details)

        # 公示区无法使用时，仅在原帖发布处罚信息。
        resolved = await self.publicity_service.resolve_channel(
            ResolvePublicityChannelQo(guild=thread.guild)
        )
        publicity_channel = resolved.channel
        publicity_fallback_reason = resolved.fallback_reason
        if publicity_channel is None:
            fallback_embed = PunishmentEmbedBuilder.create_punishment_embed(
                moderator=moderator,
                target_user=target_user,
                reason=self._QUICK_PUNISH_OFF_TOPIC_REASON,
                target_message=message,
                is_voting_allowed=True,
                mute_end_time=mute_end_time,
            )
            try:
                await self.bot.api_scheduler.submit(
                    thread.send(embed=fallback_embed),
                    priority=5,
                )
                await interaction.followup.send(
                    f"快速处罚已生效（保留投票权 + 禁言 5 分钟），"
                    f"并已降级为原帖单处公示。原因：{publicity_fallback_reason}",
                    ephemeral=True,
                )
            except Exception:
                logger.exception("快速处罚已生效，但降级公示发送失败。")
                await interaction.followup.send(
                    "快速处罚已生效，但处罚公示区不可用且原帖公示发送失败，请人工补发。",
                    ephemeral=True,
                )
            return

        public_embed = PunishmentEmbedBuilder.create_punishment_embed(
            moderator=moderator,
            target_user=target_user,
            reason=self._QUICK_PUNISH_OFF_TOPIC_REASON,
            target_message=None,
            is_voting_allowed=True,
            mute_end_time=mute_end_time,
        )
        # 复用正式公示发送流程，自动解锁子区并在发送失败时恢复状态。
        publicity = await self.publicity_service.publish(
            PublishPunishmentQo(channel=publicity_channel, embed=public_embed)
        )
        if publicity.error is not None:
            await interaction.followup.send(publicity.error, ephemeral=True)
            return
        publicity_channel = publicity.channel
        public_message = publicity.message
        assert public_message is not None

        # 统一通过转发服务选择机器人身份，使特权转发配置对快速处罚同样生效。
        evidence_warning = None
        try:
            await self.bot.api_scheduler.submit(
                self.bot.message_forward_service.forward(message, publicity_channel),
                priority=5,
            )
        except Exception as error:
            # 仅记录安全状态字段，结果不确定时提醒管理员先核查再补发。
            uncertain = isinstance(error, MessageForwardError) and error.uncertain
            logger.warning(
                "快速处罚证据转发失败 record=%s destination=%s status=%s code=%s uncertain=%s",
                result.punishment_record_id,
                publicity_channel.id,
                getattr(error, "status", None),
                getattr(error, "code", None),
                uncertain,
            )
            evidence_warning = (
                "证据消息转发结果未确认，请先检查公示区，缺失时人工补发"
                if uncertain
                else "选中消息转发失败，请人工补发"
            )

        # 将正式消息位置写回处罚记录，供历史查询使用。
        try:
            await self.logic.set_thread_punishment_publicity_message(
                result.punishment_record_id,
                guild_id=thread.guild.id,
                channel_id=publicity_channel.id,
                message_id=public_message.id,
            )
        except Exception:
            logger.exception("保存快速处罚正式公示位置失败。")

        # 正式公示成功后，再在原帖发布有效的跳转链接。
        source_embed = PunishmentEmbedBuilder.create_punishment_embed(
            moderator=moderator,
            target_user=target_user,
            reason=self._QUICK_PUNISH_OFF_TOPIC_REASON,
            target_message=None,
            is_voting_allowed=True,
            mute_end_time=mute_end_time,
            publicity_message_url=public_message.jump_url,
        )
        try:
            await self.bot.api_scheduler.submit(thread.send(embed=source_embed), priority=5)
        except Exception:
            logger.exception("快速处罚正式公示已发送，但原帖公示发送失败。")

        # 证据转发异常时提示管理员核查，避免误报材料已完整发布。
        if evidence_warning is not None:
            await interaction.followup.send(
                f"快速处罚已生效，正式公示已发送；{evidence_warning}。",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "快速处罚已生效：保留本帖投票权 + 禁言 5 分钟 + 理由「请不要歪楼滑坡」，"
            "并已完成双区公示。",
            ephemeral=True,
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

        # 查询同样使用结构化消息记录中的真实用户身份。
        target_user = await self._resolve_message_target(interaction, message)
        if target_user is None:
            return

        async with UnitOfWork(self.bot.db_handler) as uow:
            total, records = await uow.punishment_record.get_summary(
                thread_id=thread.id,
                target_user_id=target_user.id,
            )
            modal = PunishmentHistoryModal(target_user, total, records)

        await self.bot.api_scheduler.submit(
            interaction.response.send_modal(modal),
            priority=1,
        )

    @RoleGuard.requireRoles("councilModerator", "executionAuditor", "stewards")
    async def query_global_proposal_punishment_user(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
    ) -> None:
        """查看目标用户在机器人全局范围内的全部提案处罚历史摘要。"""
        if interaction.guild is None:
            await self.bot.api_scheduler.submit(
                interaction.response.send_message(
                    "此指令只能在服务器内使用。",
                    ephemeral=True,
                ),
                priority=1,
            )
            return

        async with UnitOfWork(self.bot.db_handler) as uow:
            total, records = await uow.global_proposal_punishment.get_summary(
                member.id,
                limit=4,
            )
            modal = GlobalProposalPunishmentHistoryModal(member, total, records)

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

    async def _resolve_message_target(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
    ) -> discord.User | discord.Member | None:
        """将消息作者解析为可用于处罚业务的真实 Discord 用户。"""
        try:
            # 身份解析只使用 Discord 消息元数据和已登记的结构化消息记录。
            user_id = await self.message_target_resolver.resolve_user_id(
                ResolveStructuredSpeechReferenceQo(
                    message_id=message.id,
                    author_id=message.author.id,
                    author_is_bot=message.author.bot,
                    webhook_id=message.webhook_id,
                )
            )
        except StructuredSpeechUserError as error:
            await self.bot.api_scheduler.submit(
                interaction.response.send_message(str(error), ephemeral=True),
                priority=1,
            )
            return None

        # 普通成员消息直接复用 Discord 已提供的作者对象。
        if message.webhook_id is None:
            return message.author

        guild = interaction.guild
        if guild is None:
            await self.bot.api_scheduler.submit(
                interaction.response.send_message(
                    "无法在服务器外解析结构化消息的原发言者。",
                    ephemeral=True,
                ),
                priority=1,
            )
            return None

        # 优先获取服务器成员，用户离群后再退回到全局 Discord 用户。
        target_user = guild.get_member(user_id)
        if target_user is None:
            try:
                target_user = await self.bot.api_scheduler.submit(
                    guild.fetch_member(user_id),
                    priority=1,
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                target_user = self.bot.get_user(user_id)
        if target_user is None:
            try:
                target_user = await self.bot.api_scheduler.submit(
                    self.bot.fetch_user(user_id),
                    priority=1,
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                await self.bot.api_scheduler.submit(
                    interaction.response.send_message(
                        "已找到原发言者 ID，但无法取得对应的 Discord 用户。",
                        ephemeral=True,
                    ),
                    priority=1,
                )
                return None
        return target_user
