from datetime import datetime
from typing import Optional

import discord

from StellariaPact.share.enums import PunishmentType


class PunishmentEmbedBuilder:
    PROPOSAL_VIOLATION_SCOPE = (
        "普通投票、异议投票、草案支持票、异议创建与附议、"
        "正式提案讨论帖发言、创建提案"
    )

    _PERMANENT_RESTRICTION_COPY = {
        PunishmentType.PERMANENT_VOTING: (
            "永久投票资格限制",
            "永久剥夺提案投票资格",
            "普通投票、异议投票、异议附议、草案支持票",
            "恢复提案投票资格",
        ),
        PunishmentType.PERMANENT_OBJECTION_CREATION: (
            "永久异议创建与附议限制",
            "永久剥夺异议创建与附议资格",
            "发起异议、新增异议附议",
            "恢复异议创建与附议资格",
        ),
    }

    @staticmethod
    def create_permanent_restriction_embed(
        moderator: discord.Member,
        target_user: discord.User | discord.Member,
        reason: str,
        origin_guild_name: str,
        punishment_type: PunishmentType,
        evidence_url: str | None = None,
    ) -> discord.Embed:
        """创建指定分类的永久权限处罚公示/私信 Embed。"""
        try:
            title, treatment, scope, _ = PunishmentEmbedBuilder._PERMANENT_RESTRICTION_COPY[
                punishment_type
            ]
        except KeyError as exc:
            raise ValueError("不支持的永久权限处罚分类。") from exc
        embed = discord.Embed(
            title=title,
            description=(
                f"**目标用户**: {target_user.mention}\n"
                f"**处理方式**: {treatment}\n"
                f"**影响范围**: {scope}\n"
                f"**来源服务器**: {origin_guild_name}"
            ),
            color=discord.Color.dark_red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="处罚理由", value=reason, inline=False)
        embed.add_field(name="操作人员", value=moderator.mention, inline=True)
        if evidence_url:
            embed.set_image(url=evidence_url)
        return embed

    @staticmethod
    def create_global_voting_restriction_embed(
        moderator: discord.Member,
        target_user: discord.User | discord.Member,
        reason: str,
        origin_guild_name: str,
        evidence_url: str | None = None,
    ) -> discord.Embed:
        """兼容旧调用：创建永久投票资格限制 Embed。"""
        return PunishmentEmbedBuilder.create_permanent_restriction_embed(
            moderator=moderator,
            target_user=target_user,
            reason=reason,
            origin_guild_name=origin_guild_name,
            punishment_type=PunishmentType.PERMANENT_VOTING,
            evidence_url=evidence_url,
        )

    @staticmethod
    def create_proposal_violation_embed(
        moderator: discord.Member,
        target_user: discord.User | discord.Member,
        reason: str,
        origin_guild_name: str,
        days: int,
        expires_at: datetime,
        evidence_url: str | None = None,
    ) -> discord.Embed:
        """创建限时提案违规处罚的公示/私信 Embed。"""
        expires_timestamp = int(expires_at.timestamp())
        embed = discord.Embed(
            title="提案违规处罚",
            description=(
                f"**目标用户**: {target_user.mention}\n"
                f"**处理方式**: 限制参与提案活动 {days} 天\n"
                f"**影响范围**: {PunishmentEmbedBuilder.PROPOSAL_VIOLATION_SCOPE}\n"
                f"**截止时间**: <t:{expires_timestamp}:F> (<t:{expires_timestamp}:R>)\n"
                f"**来源服务器**: {origin_guild_name}"
            ),
            color=discord.Color.dark_red(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="处罚理由", value=reason, inline=False)
        embed.add_field(name="操作人员", value=moderator.mention, inline=True)
        if evidence_url:
            embed.set_image(url=evidence_url)
        return embed

    @staticmethod
    def create_proposal_violation_lifted_embed(
        moderator: discord.Member,
        target_user: discord.User | discord.Member,
        reason: str,
        origin_guild_name: str,
        original_created_at: datetime,
        original_expires_at: datetime,
    ) -> discord.Embed:
        """创建提前解除提案违规处罚的公示/私信 Embed。"""
        created_timestamp = int(original_created_at.timestamp())
        expires_timestamp = int(original_expires_at.timestamp())
        embed = discord.Embed(
            title="提案违规处罚已解除",
            description=(
                f"**目标用户**: {target_user.mention}\n"
                "**处理方式**: 提前恢复提案参与资格\n"
                f"**原处罚时间**: <t:{created_timestamp}:F>\n"
                f"**原截止时间**: <t:{expires_timestamp}:F>\n"
                f"**来源服务器**: {origin_guild_name}"
            ),
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="解除理由", value=reason, inline=False)
        embed.add_field(name="操作人员", value=moderator.mention, inline=True)
        return embed

    @staticmethod
    def create_permanent_restriction_lifted_embed(
        moderator: discord.Member,
        target_user: discord.User | discord.Member,
        reason: str,
        origin_guild_name: str,
        original_created_at: datetime,
        punishment_type: PunishmentType,
    ) -> discord.Embed:
        """创建指定分类的永久权限限制解除公示/私信 Embed。"""
        try:
            title, _, _, treatment = PunishmentEmbedBuilder._PERMANENT_RESTRICTION_COPY[
                punishment_type
            ]
        except KeyError as exc:
            raise ValueError("不支持的永久权限处罚分类。") from exc
        original_timestamp = int(original_created_at.timestamp())
        embed = discord.Embed(
            title=f"{title}已解除",
            description=(
                f"**目标用户**: {target_user.mention}\n"
                f"**处理方式**: {treatment}\n"
                f"**原处罚时间**: <t:{original_timestamp}:F>\n"
                f"**来源服务器**: {origin_guild_name}"
            ),
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="解除理由", value=reason, inline=False)
        embed.add_field(name="操作人员", value=moderator.mention, inline=True)
        return embed

    @staticmethod
    def create_global_voting_restriction_lifted_embed(
        moderator: discord.Member,
        target_user: discord.User | discord.Member,
        reason: str,
        origin_guild_name: str,
        original_created_at: datetime,
    ) -> discord.Embed:
        """兼容旧调用：创建永久投票资格限制解除 Embed。"""
        return PunishmentEmbedBuilder.create_permanent_restriction_lifted_embed(
            moderator=moderator,
            target_user=target_user,
            reason=reason,
            origin_guild_name=origin_guild_name,
            original_created_at=original_created_at,
            punishment_type=PunishmentType.PERMANENT_VOTING,
        )

    @staticmethod
    def create_punishment_embed(
        moderator: discord.Member,
        target_user: discord.User | discord.Member,
        reason: str,
        target_message: Optional[discord.Message],
        is_voting_allowed: bool,
        mute_end_time: Optional[datetime] = None,
    ) -> discord.Embed:
        """创建处罚公示 Embed"""
        description_lines = [f"**目标用户**: {target_user.mention}"]

        if is_voting_allowed:
            description_lines.append("**处理方式**:\n保留本帖投票资格")
            color = discord.Color.orange()
        else:
            description_lines.append("**处理方式**:\n剥夺本帖投票资格")
            color = discord.Color.red()

        if mute_end_time:
            ts = int(mute_end_time.timestamp())
            description_lines.append(f"**禁言至**: <t:{ts}:F> (<t:{ts}:R>)")
        else:
            description_lines.append("**禁言状态**: 无禁言 / 已解除")

        embed = discord.Embed(
            title="议事成员资格及处罚变动公示",
            description="\n".join(description_lines),
            color=color,
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="处理理由", value=reason, inline=False)

        if target_message:
            embed.add_field(
                name="触发消息",
                value=f"[点击跳转]({target_message.jump_url})",
                inline=True,
            )

        embed.add_field(name="操作人员", value=moderator.mention, inline=True)
        return embed

    @staticmethod
    def create_unpunish_embed(
        moderator: discord.Member,
        target_user: discord.User | discord.Member,
        reason: str,
    ) -> discord.Embed:
        """创建解除处罚的公示 Embed"""
        embed = discord.Embed(
            title="议事成员处罚解除公示",
            description=(
                f"**目标用户**: {target_user.mention}\n"
                f"**处理方式**: 恢复本帖投票资格，并解除禁言限制。"
            ),
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow(),
        )
        embed.add_field(name="解除理由", value=reason, inline=False)
        embed.add_field(name="操作人员", value=moderator.mention, inline=True)
        return embed
