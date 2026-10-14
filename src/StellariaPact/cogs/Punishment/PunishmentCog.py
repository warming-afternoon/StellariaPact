import copy
import logging
import re
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
from StellariaPact.share.BusinessRuleError import BusinessRuleError
from StellariaPact.share.enums import PunishmentType
from StellariaPact.share.MessageForwardService import MessageForwardError
from StellariaPact.share.SafeDefer import safeDefer

from .constants import format_thread_mute
from .logic.PunishmentLogic import PunishmentLogic
from .logic.PunishmentPublicityService import PunishmentPublicityService
from .qo import (
    ApplyThreadPunishmentQo,
    LiftThreadPunishmentQo,
    QueryThreadPunishmentQo,
    ResolvePunishmentPanelQo,
    SavePunishmentPanelQo,
    SubmitPunishmentRemovalQo,
    SubmitQuickPunishmentQo,
    SubmitThreadPunishmentQo,
)
from .qo.PublishPunishmentQo import PublishPunishmentQo
from .qo.ResolvePublicityChannelQo import ResolvePublicityChannelQo
from .views.GlobalProposalPunishmentHistoryModal import (
    GlobalProposalPunishmentHistoryModal,
)
from .views.OffTopicConfirmationModal import OffTopicConfirmationModal
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

    # 快速处罚的档位由业务层在事务内计算。
    _QUICK_PUNISH_OFF_TOPIC_REASON = "请不要歪楼滑坡"

    def __init__(self, bot: StellariaPactBot):
        """初始化处罚业务依赖并定义消息和用户菜单。"""
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
        # 歪楼滑坡入口在有累计记录时需要确认处罚方式。
        self.quick_punish_off_topic_ctx = app_commands.ContextMenu(
            name="快速处罚-歪楼滑坡",
            callback=self.quick_punish_off_topic_message,
            type=discord.AppCommandType.message,
        )
        self.quick_punish_cumulative_ctx = app_commands.ContextMenu(
            name="快速处罚-累计处罚",
            callback=self.quick_punish_cumulative_message,
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
            callback=self.query_punishment_user,
            type=discord.AppCommandType.user,
        )

        self.query_global_proposal_punishment_ctx = app_commands.ContextMenu(
            name="查看全局提案处罚",
            callback=self.query_global_proposal_punishment_user,
            type=discord.AppCommandType.user,
        )

    def cog_load(self) -> None:
        """注册处罚右键菜单，并隔离菜单超限导致的加载失败。"""
        # 本模块占四个消息菜单，结构化发言回复占剩余一个；两个用户菜单单独计数。
        self._add_ctx_menus_safe(
            self.kick_proposal_ctx,
            self.remove_punishment_ctx,
            self.query_punishment_ctx,
            self.query_global_proposal_punishment_ctx,
            self.quick_punish_off_topic_ctx,
            self.quick_punish_cumulative_ctx,
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
            self.quick_punish_cumulative_ctx,
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
        try:
            # 临时兼容措施：旧原帖面板未登记消息 ID，需要从正式公示链接关联处罚记录。
            # TODO: 新版本运行一段时间、旧面板过渡期结束后，移除此 URL 解析及业务层回退分支。
            # 清理时同时移除 ResolvePunishmentPanelQo 的 legacy_* 字段和旧面板兼容测试。
            # 仅提取本 Bot 面板中的同服务器正式公示链接，身份解析交给业务层。
            legacy_channel_id = legacy_message_id = None
            if message.author.id == self.bot.user.id and message.webhook_id is None:
                for embed in message.embeds:
                    if embed.title != "议事成员资格及处罚变动公示":
                        continue
                    for field in embed.fields:
                        if field.name != "处罚公示":
                            continue
                        match = re.search(
                            r"https://discord\.com/channels/(\d+)/(\d+)/(\d+)", field.value
                        )
                        if match and int(match[1]) == interaction.guild_id:
                            legacy_channel_id, legacy_message_id = int(match[2]), int(match[3])
                    break
            panel = await self.logic.resolve_punishment_panel(
                ResolvePunishmentPanelQo(
                    guild_id=interaction.guild_id,
                    channel_id=message.channel.id,
                    message_id=message.id,
                    legacy_channel_id=legacy_channel_id,
                    legacy_message_id=legacy_message_id,
                )
            )

            # 面板操作定位原提案帖；普通和模板发言仍解析真实作者。
            if panel is not None:
                guild = interaction.guild
                if guild is None:
                    raise BusinessRuleError("此指令只能在服务器中使用。")
                thread = guild.get_channel_or_thread(panel.thread_id)
                if thread is None:
                    thread = await self.bot.api_scheduler.submit(
                        self.bot.fetch_channel(panel.thread_id), priority=1
                    )
                if not isinstance(thread, discord.Thread) or thread.guild.id != guild.id:
                    raise BusinessRuleError("找不到该处罚对应的提案帖子。")
                target_member = guild.get_member(panel.target_user_id) or self.bot.get_user(
                    panel.target_user_id
                )
                if target_member is None:
                    target_member = await self.bot.api_scheduler.submit(
                        self.bot.fetch_user(panel.target_user_id), priority=1
                    )
                if target_member.bot or interaction.user.id == target_member.id:
                    raise BusinessRuleError("不能对机器人或自己执行此操作。")
            else:
                if message.author.bot and message.webhook_id is None:
                    raise BusinessRuleError("无法可靠关联该处罚面板，请改用被处罚用户的发言消息。")
                target_member = await self._resolve_message_target(interaction, message)
                if target_member is None or not await self._validate_context(
                    interaction, target_member
                ):
                    return
                thread = interaction.channel

            # 业务层校验最新记录，Modal 只接收已经脱离会话的历史快照。
            history = await self.logic.get_thread_history(
                QueryThreadPunishmentQo(
                    thread_id=thread.id,
                    target_user_id=target_member.id,
                    for_removal=True,
                    selected_record_id=panel.id if panel is not None else None,
                )
            )
            modal = RemovePunishmentModal(self, target_member, thread=thread, history=history)
            await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), priority=1)
        except BusinessRuleError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
        except Exception:
            logger.exception("定位提案内处罚失败。")
            await interaction.response.send_message(
                "无法加载处罚记录，请稍后重试。", ephemeral=True
            )

    async def submit_remove_punishment(
        self,
        interaction: discord.Interaction,
        qo: SubmitPunishmentRemovalQo,
    ) -> None:
        """处理解除表单交互，并根据业务层结果发送解除公示。"""
        # 读取表单绑定的对象，并重新验证当前管理员权限。
        thread, target_user = qo.thread, qo.target_user
        reason, expected_record_id = qo.reason, qo.expected_record_id
        # 表单提交时再次校验权限和服务器，避免沿用打开时的权限。
        if not RoleGuard.hasRoles(interaction, "councilModerator", "stewards"):
            await interaction.response.send_message("你没有解除处罚的权限。", ephemeral=True)
            return
        if interaction.guild_id != thread.guild.id:
            await interaction.response.send_message("无法跨服务器解除提案处罚。", ephemeral=True)
            return
        await safeDefer(interaction, ephemeral=True)

        # 业务层只接收解除条件，数据库失败和过期表单由控制器回应。
        try:
            count = await self.logic.lift_thread_punishment(
                LiftThreadPunishmentQo(
                    thread_id=thread.id,
                    target_user_id=target_user.id,
                    expected_record_id=expected_record_id,
                    moderator_id=interaction.user.id,
                    reason=reason,
                )
            )
        except BusinessRuleError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        except Exception:
            logger.exception("执行解除提案内处罚失败。")
            await interaction.followup.send("解除处罚失败，请稍后重试。", ephemeral=True)
            return

        # 已完成的解除不因公示发送失败回滚。
        embed = PunishmentEmbedBuilder.create_unpunish_embed(interaction.user, target_user, reason)
        embed.add_field(name="当前累计处罚", value=f"{count} 次", inline=False)
        try:
            await self.bot.api_scheduler.submit(thread.send(embed=embed), priority=5)
        except Exception:
            logger.exception("处罚已解除，但原帖解除公示发送失败。")
            await interaction.followup.send(
                f"处罚已解除，当前累计处罚 {count} 次；公示发送失败，请人工补发。", ephemeral=True
            )
            return
        await interaction.followup.send(f"处罚已解除，当前累计处罚 {count} 次。", ephemeral=True)

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
            cog=self,
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

        # 通过历史快照读取累计次数，控制器不持有数据库会话。
        history = await self.logic.get_thread_history(
            QueryThreadPunishmentQo(
                thread_id=interaction.channel.id, target_user_id=target_user.id
            )
        )
        count = history.cumulative_count
        if count:
            modal = OffTopicConfirmationModal(self, target_user, message, count)
            await self.bot.api_scheduler.submit(interaction.response.send_modal(modal), priority=1)
            return
        await self.execute_quick_punishment(
            interaction, SubmitQuickPunishmentQo(message, target_user, cumulative=False)
        )

    @RoleGuard.requireRoles("councilModerator", "stewards")
    async def quick_punish_cumulative_message(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
    ) -> None:
        """对选中消息的真实作者执行累计处罚。"""
        target_user = await self._resolve_message_target(interaction, message)
        if target_user is None or not await self._validate_context(interaction, target_user):
            return
        await self.execute_quick_punishment(
            interaction, SubmitQuickPunishmentQo(message, target_user, cumulative=True)
        )

    async def submit_manual_punishment(
        self,
        interaction: discord.Interaction,
        qo: SubmitThreadPunishmentQo,
    ) -> None:
        """校验人工处罚表单，并协调业务事务、证据转发及双区公示。"""
        if not RoleGuard.hasRoles(interaction, "councilModerator", "stewards"):
            await interaction.response.send_message("你没有执行处罚的权限。", ephemeral=True)
            return
        await safeDefer(interaction, ephemeral=True)

        try:
            # 解析数据
            allow_voting_str = qo.voting_input.strip()
            if allow_voting_str == "是":
                is_voting_allowed = True
            elif allow_voting_str == "否":
                is_voting_allowed = False
            else:
                return await interaction.followup.send(
                    "“是否保留投票权”字段必须输入“是”或“否”。",
                    ephemeral=True,
                )

            try:
                mute_minutes = int(qo.mute_minutes_input)
                if mute_minutes < 0:
                    raise ValueError()
            except ValueError:
                return await interaction.followup.send(
                    "禁言时长必须是一个有效的非负整数。",
                    ephemeral=True,
                )

            reason = qo.reason
            thread = interaction.channel
            moderator = interaction.user

            if not isinstance(thread, discord.Thread) or not isinstance(moderator, discord.Member):
                return

            # 公示预检及附件读取在提交处罚前完成，失败时不产生半成品记录。
            resolved = await self.publicity_service.resolve_channel(
                ResolvePublicityChannelQo(guild=thread.guild)
            )
            publicity_channel, publicity_fallback_reason = (
                resolved.channel,
                resolved.fallback_reason,
            )
            files: list[discord.File] = []
            if publicity_channel is not None:
                try:
                    for attachment in qo.evidence:
                        files.append(await attachment.to_file())
                except Exception:
                    for file in files:
                        file.close()
                    raise

            # 计算截止时间（UTC aware datetime）
            mute_end_time = None
            if mute_minutes > 0:
                mute_end_time = datetime.now(timezone.utc) + timedelta(minutes=mute_minutes)

            # 资格状态、处罚记录和进行中投票的清理在同一事务内完成。
            try:
                result = await self.logic.apply_thread_punishment(
                    ApplyThreadPunishmentQo(
                        guild_id=thread.guild.id,
                        thread_id=thread.id,
                        target_user_id=qo.target_user.id,
                        moderator_id=moderator.id,
                        reason=reason,
                        source_message_url=(
                            qo.target_message.jump_url if qo.target_message is not None else None
                        ),
                        voting_allowed=is_voting_allowed,
                        mute_end_time=mute_end_time,
                    )
                )
            except Exception:
                for file in files:
                    file.close()
                raise

            if publicity_channel is None:
                fallback_embed = PunishmentEmbedBuilder.create_punishment_embed(
                    moderator=moderator,
                    target_user=qo.target_user,
                    reason=reason,
                    target_message=qo.target_message,
                    is_voting_allowed=is_voting_allowed,
                    mute_end_time=mute_end_time,
                )
                try:
                    source_message = await self.bot.api_scheduler.submit(
                        thread.send(embed=fallback_embed),
                        priority=5,
                    )
                    await self._save_panel_location(
                        SavePunishmentPanelQo(
                            record_id=result.punishment_record_id,
                            guild_id=thread.guild.id,
                            channel_id=thread.id,
                            message_id=source_message.id,
                            is_source=True,
                        )
                    )
                    material_warning = "；上传的处罚材料未发布" if qo.evidence else ""
                    await interaction.followup.send(
                        f"处罚已生效，并已降级为原帖单处公示{material_warning}。"
                        f"原因：{publicity_fallback_reason}",
                        ephemeral=True,
                    )
                except Exception:
                    logger.exception("帖子内处罚已生效，但降级公示发送失败。")
                    await interaction.followup.send(
                        "处罚已生效，但处罚公示区不可用且原帖公示发送失败，请人工补发。",
                        ephemeral=True,
                    )
                return

            public_embed = PunishmentEmbedBuilder.create_punishment_embed(
                moderator=moderator,
                target_user=qo.target_user,
                reason=reason,
                target_message=None,
                is_voting_allowed=is_voting_allowed,
                mute_end_time=mute_end_time,
            )
            # 通过共享服务发送正式公示，附件由当前表单统一释放。
            try:
                publicity = await self.publicity_service.publish(
                    PublishPunishmentQo(
                        channel=publicity_channel,
                        embed=public_embed,
                        files=tuple(files),
                    )
                )
            finally:
                for file in files:
                    file.close()
            if publicity.error is not None:
                await interaction.followup.send(publicity.error, ephemeral=True)
                return
            publicity_channel = publicity.channel
            public_message = publicity.message
            assert public_message is not None

            # 通过转发服务选择机器人身份，并保留结果不确定时的提示。
            evidence_forward_failed = False
            evidence_forward_uncertain = False
            if qo.target_message is not None:
                try:
                    forwarded_id = await self.bot.api_scheduler.submit(
                        self.bot.message_forward_service.forward(
                            qo.target_message, publicity_channel
                        ),
                        priority=5,
                    )
                    logger.info(
                        "处罚证据转发成功 record=%s source_channel=%s source_message=%s "
                        "destination=%s forwarded_message=%s",
                        result.punishment_record_id,
                        qo.target_message.channel.id,
                        qo.target_message.id,
                        publicity_channel.id,
                        forwarded_id,
                    )
                except Exception as error:
                    evidence_forward_failed = True
                    evidence_forward_uncertain = (
                        isinstance(error, MessageForwardError) and error.uncertain
                    )
                    logger.warning(
                        "处罚证据转发失败 record=%s source_channel=%s source_message=%s "
                        "destination=%s status=%s code=%s uncertain=%s",
                        result.punishment_record_id,
                        qo.target_message.channel.id,
                        qo.target_message.id,
                        publicity_channel.id,
                        getattr(error, "status", None),
                        getattr(error, "code", None),
                        evidence_forward_uncertain,
                    )

            # 正式公示和原帖公示统一通过位置 Qo 登记。
            location_saved = await self._save_panel_location(
                SavePunishmentPanelQo(
                    record_id=result.punishment_record_id,
                    guild_id=thread.guild.id,
                    channel_id=publicity_channel.id,
                    message_id=public_message.id,
                )
            )

            source_embed = PunishmentEmbedBuilder.create_punishment_embed(
                moderator=moderator,
                target_user=qo.target_user,
                reason=reason,
                target_message=None,
                is_voting_allowed=is_voting_allowed,
                mute_end_time=mute_end_time,
                publicity_message_url=public_message.jump_url,
            )
            source_sent = True
            try:
                source_message = await self.bot.api_scheduler.submit(
                    thread.send(embed=source_embed), priority=5
                )
                await self._save_panel_location(
                    SavePunishmentPanelQo(
                        record_id=result.punishment_record_id,
                        guild_id=thread.guild.id,
                        channel_id=thread.id,
                        message_id=source_message.id,
                        is_source=True,
                    )
                )
            except Exception:
                source_sent = False
                logger.exception("帖子内处罚正式公示已发送，但原帖公示发送失败。")

            warnings: list[str] = []
            if evidence_forward_uncertain:
                warnings.append("证据消息转发结果未确认，请先检查公示区，缺失时人工补发")
            elif evidence_forward_failed:
                warnings.append("选中消息转发失败，请人工补发")
            if not location_saved:
                warnings.append("历史记录未能保存正式公示链接")
            if not source_sent:
                warnings.append("原帖公示发送失败")
            if warnings:
                await interaction.followup.send(
                    f"处罚已生效，正式公示已发送；{'；'.join(warnings)}，请人工检查。",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send("已成功处罚并完成双区公示。", ephemeral=True)

        except Exception as e:
            logger.error(f"处理处罚模态框时发生错误: {e}", exc_info=True)
            await interaction.followup.send("处理请求时发生错误，请联系技术人员。", ephemeral=True)

    async def execute_quick_punishment(
        self,
        interaction: discord.Interaction,
        qo: SubmitQuickPunishmentQo,
    ) -> None:
        """统一执行快速处罚及双区公示，表单提交时再次验证上下文。"""
        # 消息菜单和确认表单共用独立输入参数，后续流程保持一致。
        message, target_user = qo.message, qo.target_user
        if not RoleGuard.hasRoles(interaction, "councilModerator", "stewards"):
            await interaction.response.send_message("你没有执行处罚的权限。", ephemeral=True)
            return
        if interaction.channel_id != message.channel.id:
            await interaction.response.send_message("处罚表单与原消息帖子不一致。", ephemeral=True)
            return
        if not await self._validate_context(interaction, target_user):
            return
        await safeDefer(interaction, ephemeral=True)
        thread, moderator = interaction.channel, interaction.user
        assert isinstance(thread, discord.Thread) and isinstance(moderator, discord.Member)
        try:
            result = await self.logic.apply_thread_punishment(
                ApplyThreadPunishmentQo(
                    guild_id=thread.guild.id,
                    thread_id=thread.id,
                    target_user_id=target_user.id,
                    moderator_id=moderator.id,
                    reason=self._QUICK_PUNISH_OFF_TOPIC_REASON,
                    source_message_url=message.jump_url,
                    voting_allowed=True,
                    mute_end_time=None,
                    quick_mode="cumulative" if qo.cumulative else "off_topic",
                    off_topic_confirmed=qo.off_topic_confirmed,
                )
            )
        except BusinessRuleError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        except Exception:
            logger.exception("执行快速处罚失败。")
            await interaction.followup.send("快速处罚失败，请稍后重试。", ephemeral=True)
            return
        reason, mute_end_time = result.reason, result.mute_end_time
        voting_allowed = result.voting_allowed
        treatment = "保留本帖投票权" if voting_allowed else "保留已有的本帖投票权限制"
        summary = (
            f"快速处罚已生效：{treatment}；{format_thread_mute(mute_end_time)}；"
            f"理由「{reason}」；当前累计处罚 {result.cumulative_count} 次"
        )

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
                reason=reason,
                target_message=message,
                is_voting_allowed=voting_allowed,
                mute_end_time=mute_end_time,
            )
            try:
                source_message = await self.bot.api_scheduler.submit(
                    thread.send(embed=fallback_embed),
                    priority=5,
                )
                await self._save_panel_location(
                    SavePunishmentPanelQo(
                        record_id=result.punishment_record_id,
                        guild_id=thread.guild.id,
                        channel_id=thread.id,
                        message_id=source_message.id,
                        is_source=True,
                    )
                )
                await interaction.followup.send(
                    f"{summary}，并已降级为原帖单处公示。原因：{publicity_fallback_reason}",
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
            reason=reason,
            target_message=None,
            is_voting_allowed=voting_allowed,
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

        warnings: list[str] = []
        # 将正式消息位置写回处罚记录，供历史查询使用。
        if not await self._save_panel_location(
            SavePunishmentPanelQo(
                record_id=result.punishment_record_id,
                guild_id=thread.guild.id,
                channel_id=publicity_channel.id,
                message_id=public_message.id,
            )
        ):
            warnings.append("历史记录未能保存正式公示链接")

        # 正式公示成功后，再在原帖发布有效的跳转链接。
        source_embed = PunishmentEmbedBuilder.create_punishment_embed(
            moderator=moderator,
            target_user=target_user,
            reason=reason,
            target_message=None,
            is_voting_allowed=voting_allowed,
            mute_end_time=mute_end_time,
            publicity_message_url=public_message.jump_url,
        )
        try:
            source_message = await self.bot.api_scheduler.submit(
                thread.send(embed=source_embed), priority=5
            )
            await self._save_panel_location(
                SavePunishmentPanelQo(
                    record_id=result.punishment_record_id,
                    guild_id=thread.guild.id,
                    channel_id=thread.id,
                    message_id=source_message.id,
                    is_source=True,
                )
            )
        except Exception:
            logger.exception("快速处罚正式公示已发送，但原帖公示发送失败。")
            warnings.append("原帖公示发送失败，请人工补发")

        # 证据转发异常时提示管理员核查，避免误报材料已完整发布。
        if evidence_warning is not None:
            warnings.append(evidence_warning)
        if warnings:
            await interaction.followup.send(
                f"{summary}；正式公示已发送；{'；'.join(warnings)}。",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"{summary}，并已完成双区公示。",
            ephemeral=True,
        )

    async def _save_panel_location(self, qo: SavePunishmentPanelQo) -> bool:
        """统一登记两处处罚面板，保存失败时保留已发送的公示。"""
        # 两类面板共用事务入口，避免控制器重复组织数据库操作。
        try:
            await self.logic.save_publicity_panel(qo)
        except Exception:
            # 返回保存结果，由当前公示流程决定对管理员的提示。
            logger.exception(
                "保存处罚面板位置失败，记录 %s，原帖面板 %s。", qo.record_id, qo.is_source
            )
            return False
        return True

    @RoleGuard.requireRoles("councilModerator", "stewards")
    async def query_punishment_user(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
    ):
        """[议事督导/管理组] 查询头像选中用户在当前帖子的处罚历史。"""
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

        target_user = member

        # 在业务层完成查询和快照转换，视图只负责展示。
        history = await self.logic.get_thread_history(
            QueryThreadPunishmentQo(thread_id=thread.id, target_user_id=target_user.id)
        )
        modal = PunishmentHistoryModal(target_user, history)

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
