from datetime import datetime, timezone
from typing import Dict
from zoneinfo import ZoneInfo

import discord

from ....share.enums.ConfirmationStatus import ConfirmationStatus
from ..qo.BuildAdminReviewEmbedQo import BuildAdminReviewEmbedQo
from ..qo.BuildCollectionExpiredEmbedQo import BuildCollectionExpiredEmbedQo
from ..qo.BuildConfirmationEmbedQo import BuildConfirmationEmbedQo
from ..qo.BuildFirstObjectionEmbedQo import BuildFirstObjectionEmbedQo
from ..qo.BuildObjectionReviewResultEmbedQo import \
    BuildObjectionReviewResultEmbedQo
from ..qo.BuildProposalFrozenEmbedQo import BuildProposalFrozenEmbedQo
from ..qo.BuildVoteResultEmbedQo import BuildVoteResultEmbedQo


class ModerationEmbedBuilder:
    """
    构建议事管理相关操作的 Embed 消息。
    """

    @staticmethod
    def build_confirmation_embed(
        qo: "BuildConfirmationEmbedQo", bot_user: discord.ClientUser
    ) -> discord.Embed:
        """
        根据确认会话状态构建Embed。
        """
        title = "⏳ 流程确认中：进入执行阶段"
        color = discord.Color.yellow()

        if qo.status == ConfirmationStatus.COMPLETED:
            title = "✅ 确认完成：提案已进入执行阶段"
            color = discord.Color.green()
        elif qo.status == ConfirmationStatus.CANCELED:
            title = "❌ 操作已取消"
            color = discord.Color.red()

        embed = discord.Embed(title=title, color=color)

        if qo.status == ConfirmationStatus.CANCELED and qo.canceler_id:
            embed.description = f"操作由 <@{qo.canceler_id}> 取消。"

        confirmed_lines = []
        pending_lines = []

        # 获取角色名称和确认者ID
        confirmed_parties: Dict[str, int] = qo.confirmed_parties

        for role_key in qo.required_roles:
            role_name = qo.role_display_names.get(role_key, role_key)
            user_id = confirmed_parties.get(role_key)
            if user_id:
                confirmed_lines.append(f"✅ **{role_name}**: <@{user_id}>")
            else:
                pending_lines.append(f"⏳ **{role_name}**: 待确认")

        confirmed_field_value = "\n".join(confirmed_lines) if confirmed_lines else "无"
        embed.add_field(name="已确认方", value=confirmed_field_value, inline=False)

        if pending_lines:
            pending_field_value = "\n".join(pending_lines)
            embed.add_field(name="待确认方", value=pending_field_value, inline=False)
        return embed

    @staticmethod
    def build_status_change_embed(
        thread_name: str,
        new_status: str,
        moderator: discord.User | discord.Member,
        reason: str | None = None,
    ) -> discord.Embed:
        """
        构建状态变更通知的Embed。
        """
        embed = discord.Embed(
            title=f"📢 提案状态变更: {thread_name}",
            description=f"提案的状态已被 {moderator.mention} 变更为{new_status}",
            color=discord.Color.orange(),
        )
        if reason:
            embed.add_field(name="原因", value=reason, inline=False)
        embed.timestamp = datetime.now(timezone.utc)
        return embed

    @staticmethod
    def create_kick_embed(
        moderator: discord.Member,
        kicked_user: discord.User | discord.Member,
        reason: str,
        target_message: discord.Message,
    ) -> discord.Embed:
        """
        创建踢出提案的处罚公示 Embed。
        """
        embed = discord.Embed(
            title="议事成员资格变动公示",
            description=f"**目标用户**: {kicked_user.mention}\n**处理方式**: 剥夺本帖议事资格",
            color=discord.Color.red(),
            timestamp=datetime.now(ZoneInfo("UTC")),
        )
        embed.add_field(name="处理理由", value=reason, inline=False)
        embed.add_field(
            name="相关消息", value=f"[点击跳转]({target_message.jump_url})", inline=True
        )
        embed.add_field(name="操作人员", value=moderator.mention, inline=True)
        return embed

    @staticmethod
    def build_admin_review_embed(
        qo: "BuildAdminReviewEmbedQo", bot_user: discord.ClientUser
    ) -> discord.Embed:
        """
        构建管理员审核异议的 Embed 消息。
        """
        embed = discord.Embed(
            title="新的异议需要审核",
            description=(
                f"针对提案 [{qo.proposal_title}]"
                f"(https://discord.com/channels/{qo.guild_id}/{qo.proposal_thread_id}) "
                "的一项新异议需要管理员审核\n"
                f"异议发起人: <@{qo.objector_id}>"
            ),
            color=discord.Color.orange(),
        )
        embed.add_field(name="异议理由", value=f"{qo.objection_reason}", inline=False)
        return embed

    @staticmethod
    def build_first_objection_embed(
        qo: "BuildFirstObjectionEmbedQo",
    ) -> discord.Embed:
        """
        构建首次异议的 Embed 消息，用于发起投票。
        """
        embed = discord.Embed(
            title="异议产生票收集中",
            description=(
                f"对提案 [{qo.proposal_title}]({qo.proposal_url}) 的一项异议"
                "需要收集足够的支持票以进入正式讨论阶段。\n\n"
                f"**异议发起人**: <@{qo.objector_id}> ({qo.objector_display_name})"
            ),
            color=discord.Color.yellow(),
        )
        embed.add_field(name="异议理由", value=f"{qo.objection_reason}", inline=False)
        embed.add_field(name="所需票数", value=str(qo.required_votes), inline=True)
        embed.add_field(name="当前支持", value=f"0 / {qo.required_votes}", inline=True)
        return embed

    @staticmethod
    def build_proposal_frozen_embed(qo: "BuildProposalFrozenEmbedQo") -> discord.Embed:
        """
        构建提案冻结的通知 Embed。
        """
        embed = discord.Embed(
            title="提案已冻结",
            description=(
                "由于一项异议已获得足够的支持票，该提案现已进入冻结状态。\n"
                "在相关异议得到处理之前，原提案的投票和讨论将暂停。"
            ),
            color=discord.Color.orange(),
        )
        embed.add_field(
            name="相关异议帖",
            value=f"[点击跳转至异议帖]({qo.objection_thread_jump_url})",
            inline=False,
        )
        embed.set_footer(text="请在异议帖中继续进行讨论和投票。")
        return embed

    @staticmethod
    def build_vote_result_embed(
        qo: "BuildVoteResultEmbedQo", bot_user: discord.ClientUser
    ) -> discord.Embed:
        """
        构建异议投票结果的 Embed 消息。
        """
        result_text = "通过" if qo.is_passed else "被否决"
        result_color = discord.Color.green() if qo.is_passed else discord.Color.red()
        embed = discord.Embed(
            title=f"异议投票结果：{result_text}",
            description=(
                f"关于提案 **[{qo.proposal_title}]({qo.proposal_thread_url})** "
                f"的异议投票已结束。\n\n"
                f"**异议发起人**: <@{qo.objector_id}>"
            ),
            color=result_color,
        )
        if qo.objection_thread_url:
            embed.add_field(
                name="异议帖",
                value=f"[点击跳转]({qo.objection_thread_url})",
                inline=False,
            )
        
        embed.add_field(name="异议理由", value=f"{qo.objection_reason}", inline=False)
        
        embed.add_field(name="赞成票", value=str(qo.approve_votes), inline=True)
        embed.add_field(name="反对票", value=str(qo.reject_votes), inline=True)
        embed.add_field(name="总票数", value=str(qo.total_votes), inline=True)
        
        embed.timestamp = datetime.now(timezone.utc)
        return embed

    @staticmethod
    def build_collection_expired_embed(
        qo: "BuildCollectionExpiredEmbedQo",
    ) -> discord.Embed:
        """
        构建异议产生票收集失败的 Embed 消息。
        """
        embed = discord.Embed(
            title="异议产生票收集失败",
            description=(
                f"对提案 [{qo.proposal_title}]({qo.proposal_url}) 的一项异议"
                "因未能在指定时间内收集到足够的支持票而关闭。\n\n"
                f"**异议发起人**: <@{qo.objector_id}>"
            ),
            color=discord.Color.red(),
        )
        embed.add_field(name="异议理由", value=f"{qo.objection_reason}", inline=False)
        embed.add_field(name="所需票数", value=str(qo.required_votes), inline=True)
        embed.add_field(
            name="最终支持数", value=f"{qo.final_votes} / {qo.required_votes}", inline=True
        )
        embed.timestamp = datetime.now(timezone.utc)
        return embed

    @staticmethod
    def build_objection_review_result_embed(
        qo: "BuildObjectionReviewResultEmbedQo",
    ) -> discord.Embed:
        """
        构建异议审核结果的 Embed 消息。
        """
        action_text = "批准" if qo.is_approve else "驳回"
        color = discord.Color.green() if qo.is_approve else discord.Color.red()

        embed = discord.Embed(
            title=f"异议审核结果：{action_text}",
            description=(
                f"针对提案 [{qo.proposal_title}]"
                f"(https://discord.com/channels/{qo.guild_id}/{qo.proposal_thread_id}) "
                "的异议已由管理员审核。"
            ),
            color=color,
        )

        embed.add_field(name="异议发起人", value=f"<@{qo.objector_id}>", inline=True)
        embed.add_field(name="审核管理员", value=f"<@{qo.moderator_id}>", inline=True)
        embed.add_field(
            name="原异议理由", value=f"{qo.objection_reason}", inline=False
        )
        embed.add_field(
            name="管理员审核理由", value=f"{qo.review_reason}", inline=False
        )

        return embed

    @staticmethod
    def build_voter_list_embeds(
        title: str, voter_ids: list[int], color: discord.Color
    ) -> list[discord.Embed]:
        """
        将一个长的投票者列表分割成多个 Embed。
        """
        embeds = []
        # 每 40 个 ID 创建一个 Embed，以确保不超过字符限制
        chunk_size = 40
        
        for i in range(0, len(voter_ids), chunk_size):
            chunk = voter_ids[i : i + chunk_size]
            description = "\n".join(f"<@{user_id}>" for user_id in chunk)
            
            embed = discord.Embed(
                title=f"{title} ({i + 1} - {i + len(chunk)})",
                description=description,
                color=color,
            )
            embeds.append(embed)
            
        return embeds

