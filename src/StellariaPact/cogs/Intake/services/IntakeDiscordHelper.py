from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from StellariaPact.cogs.Intake.views.IntakeEmbedBuilder import IntakeEmbedBuilder
from StellariaPact.cogs.Intake.views.IntakeSupportView import IntakeSupportView
from StellariaPact.cogs.Moderation.qo import BuildConfirmationEmbedQo
from StellariaPact.cogs.Moderation.views.ConfirmationView import ConfirmationView
from StellariaPact.cogs.Moderation.views.ModerationEmbedBuilder import ModerationEmbedBuilder
from StellariaPact.dto.ProposalIntakeDto import ProposalIntakeDto
from StellariaPact.share import DiscordUtils
from StellariaPact.share.enums import IntakeStatus
from StellariaPact.share.ProposalContentFormatter import ProposalContentFormatter
from StellariaPact.share.UnitOfWork import UnitOfWork

if TYPE_CHECKING:
    from StellariaPact.dto import ConfirmationSessionDto
    from StellariaPact.share.StellariaPactBot import StellariaPactBot

logger = logging.getLogger(__name__)


class IntakeDiscordHelper:
    """专门负责处理与 Intake 相关的 Discord API 交互（更新消息、修改标签等）"""

    def __init__(self, bot: "StellariaPactBot"):
        self.bot = bot

    # -------------------------
    # 状态显示映射
    # -------------------------

    @staticmethod
    def get_review_result_text(status: int) -> str:
        """根据状态获取审核结果文本。"""
        result_map = {
            int(IntakeStatus.SUPPORT_COLLECTING): "审核通过",
            int(IntakeStatus.REJECTED): "审核拒绝",
            int(IntakeStatus.MODIFICATION_REQUIRED): "要求修改",
            int(IntakeStatus.APPROVED): "支持票达标，等待提案委员确认",
        }
        return result_map.get(status, "状态更新")

    @staticmethod
    def get_tag_name_for_status(status: int) -> str | None:
        """根据状态获取对应的标签键名"""
        status_tag_map = {
            int(IntakeStatus.PENDING_REVIEW): "pending_review",
            int(IntakeStatus.SUPPORT_COLLECTING): "support_collecting",
            int(IntakeStatus.APPROVED): "approved",
            int(IntakeStatus.REJECTED): "rejected",
            int(IntakeStatus.MODIFICATION_REQUIRED): "modification_required",
        }
        return status_tag_map.get(status)

    @staticmethod
    def get_title_prefix_for_status(status: int) -> str | None:
        """根据状态获取审核帖标题前缀"""
        status_prefix_map = {
            int(IntakeStatus.PENDING_REVIEW): "[待审核]",
            int(IntakeStatus.SUPPORT_COLLECTING): "[已通过]",
            int(IntakeStatus.APPROVED): "[已发布]",
            int(IntakeStatus.REJECTED): "[未通过]",
            int(IntakeStatus.MODIFICATION_REQUIRED): "[需要修改]",
        }
        return status_prefix_map.get(status)

    def resolve_forum_tag(
        self, forum: discord.ForumChannel, raw_tag_id: int | str | None, tag_key: str
    ) -> discord.ForumTag | None:
        """根据配置中的标签 ID 解析论坛标签。"""
        if raw_tag_id is None:
            return None

        try:
            tag_id = int(raw_tag_id)
        except (TypeError, ValueError):
            logger.warning(f"config.tags.{tag_key} 配置值无效: {raw_tag_id}")
            return None

        tag = next((item for item in forum.available_tags if item.id == tag_id), None)
        if tag is None:
            logger.warning(
                f"在论坛 {forum.id} 的可用标签中未找到 ID 为 {tag_id} 的 {tag_key} 标签。"
            )
            return None

        return tag

    # -------------------------
    # 更新审核帖消息与标签
    # -------------------------

    async def update_review_thread_message(
        self,
        intake_dto: ProposalIntakeDto,
        view: discord.ui.View | None,
        extra_note: str | None = None,
        notify_proposer: bool = False,
    ):
        """更新审核帖子首楼内容，并在需要时通知提案人。"""
        if not intake_dto.review_thread_id:
            logger.warning(f"草案 {intake_dto.id} 缺少 review_thread_id，无法更新消息。")
            return

        thread = await DiscordUtils.fetch_thread(self.bot, intake_dto.review_thread_id)
        if not isinstance(thread, discord.Thread):
            logger.warning(f"草案 {intake_dto.id} 的 review_thread_id 无效。")
            return

        try:
            msg = await thread.fetch_message(thread.id)

            submitted_ts = int(msg.created_at.timestamp())
            status_text = self.get_review_result_text(intake_dto.status)
            status_emoji = {
                int(IntakeStatus.SUPPORT_COLLECTING): "✅",
                int(IntakeStatus.REJECTED): "❌",
                int(IntakeStatus.MODIFICATION_REQUIRED): "🟡",
                int(IntakeStatus.APPROVED): "🎉",
            }.get(intake_dto.status, "ℹ️")

            review_body = ProposalContentFormatter.format_review_body(
                intake_dto, submitted_ts, id_label="议案ID"
            )
            lines = [
                review_body,
                "",
                f"{status_emoji} **状态：** {status_text}\n",
                f"💬 **审核意见：** {intake_dto.review_comment or '（无）'}",
            ]

            if extra_note:
                lines.extend(["", f"ℹ️ {extra_note}"])

            await msg.edit(content="\n".join(lines), embed=None, view=view)

            if notify_proposer and intake_dto.reviewer_id and intake_dto.reviewed_at:
                notify_lines = [
                    f"<@{intake_dto.author_id}> 您的议案已被审核！",
                    "## 📋 审核记录",
                    f"{status_emoji} **审核结果：** {status_text}",
                    "",
                    "💬 **审核意见：**",
                    intake_dto.review_comment or "（无）",
                    "---",
                    "📝 如有疑问，申请人可联系管理组了解详细情况。",
                ]
                await thread.send("\n".join(notify_lines))

        except discord.NotFound:
            logger.error(f"无法在帖子 {thread.id} 中找到起始消息。")
        except discord.Forbidden:
            logger.error(f"没有权限编辑帖子 {thread.id} 中的消息。")

    async def update_review_thread_tags(self, intake_dto: ProposalIntakeDto):
        """更新审核帖子的标签和标题前缀"""
        if not intake_dto.review_thread_id:
            logger.warning(f"草案 {intake_dto.id} 缺少 review_thread_id，无法更新标签。")
            return

        thread = await DiscordUtils.fetch_thread(self.bot, intake_dto.review_thread_id)
        if not thread:
            logger.warning(f"草案 {intake_dto.id} 的 review_thread_id 无效。")
            return

        forum = thread.parent
        if not isinstance(forum, discord.ForumChannel):
            logger.warning(f"帖子 {thread.id} 的父频道不是论坛频道。")
            return

        target_tag_name = self.get_tag_name_for_status(intake_dto.status)
        if not target_tag_name:
            logger.warning(f"草案 {intake_dto.id} 的状态 {intake_dto.status} 没有对应的标签。")
            return

        # 构建用于 intake_tags 的配置
        config = {
            "tags": self.bot.config.get("intake_tags", {}),
            "status_tag_keys": self.bot.config.get("intake_status_tag_keys", []),
        }

        new_tags = DiscordUtils.calculate_new_tags(
            current_tags=thread.applied_tags,
            forum_tags=forum.available_tags,
            config=config,
            target_tag_name=target_tag_name,
        )

        edit_payload = {}

        title_prefix = self.get_title_prefix_for_status(intake_dto.status)
        new_title = f"{title_prefix} {intake_dto.title}" if title_prefix else intake_dto.title

        # 确保标题长度不超过 Discord 限制（100 个字符）
        if len(new_title) > 100:
            new_title = new_title[:97] + "..."

        if new_title != thread.name:
            edit_payload["name"] = new_title

        if new_tags is not None:
            edit_payload["applied_tags"] = new_tags

        if not edit_payload:
            return

        try:
            await thread.edit(**edit_payload)
        except discord.Forbidden:
            logger.error(f"没有权限编辑帖子 {thread.id} 的标签或标题。")
        except Exception as e:
            logger.error(f"更新帖子 {thread.id} 的标签或标题时出错: {e}")

    # -------------------------
    # 更新公示频道的支持票收集面板
    # -------------------------

    async def update_support_message(self, intake: ProposalIntakeDto, current_votes: int):
        """更新公示频道中的发布票收集面板"""
        if not intake.voting_message_id:
            return

        channels_config = self.bot.config.get("channels", {})
        channel = await DiscordUtils.fetch_channel(
            self.bot, channels_config.get("objection_publicity")
        )
        if not isinstance(channel, discord.TextChannel):
            return

        try:
            msg = await channel.fetch_message(intake.voting_message_id)
            embed = IntakeEmbedBuilder.build_support_embed(intake, current_votes=current_votes)
            await msg.edit(embed=embed, view=IntakeSupportView(self.bot))
        except discord.NotFound:
            logger.warning(f"找不到支持票消息 {intake.voting_message_id}，跳过更新。")
        except discord.Forbidden:
            logger.error(f"没有权限编辑支持票消息 {intake.voting_message_id}。")
        except Exception as e:
            logger.warning(f"更新支持票面板失败 {intake.voting_message_id}: {e}")

    # -------------------------
    # 讨论帖参与准则
    # -------------------------

    @staticmethod
    async def post_discussion_rules(thread: discord.Thread) -> None:
        """在讨论帖发送参与准则作为第二条消息。"""
        rules = (
            "📌 **提案区参与准则（简要版）**\n"
            "💡 请各位成员理性讨论，共同维护良好氛围。\n\n"
            "🚩 **违规界定**\n"
            "🛑 **一类违规（严重干扰）**\n"
            "严禁发布违规信息（键政/广告/色情/暴力）。\n"
            "严禁人身攻击、引战及恶意破坏讨论流程。\n"
            "严禁恶意刷票、私下施压等操纵行为。\n"
            "严禁断章取义、误导讨论走向。\n\n"
            "❌ **二类违规（中度干扰）**\n"
            "不得持续偏题、使用阴阳怪气言论。\n"
            "拒绝配合管理提醒将加重处罚。\n"
            "禁止恶意刷屏、干扰正常讨论。\n\n"
            "⛔ **三类违规（一般干扰）**\n"
            "避免偏题或情绪化争吵。\n"
            "避免「大字报」及干扰排版的格式。\n"
            "避免无实质内容的无效水贴。\n\n"
            "⚖️ **违规处理**\n"
            "处理措施：包括但不限于口头警告、删除消息、临时/长时禁言或踢出提案并剥夺投票权等。多次违规将加重处理。\n"
            "管理规范：管理人员遵循身份唯一原则。参与讨论的管理人员不具备该提案的管理权，严禁利用职权打压异见。\n\n"
            "📖 详细规则请点击：📜｜社区制度。\n\n"
            "*(本提醒由机器人自动发送，若发现违规请直接 @提案委员处理)*"
        )
        try:
            await thread.send(rules)
        except Exception as e:
            logger.error(f"发送讨论规则失败 (帖子 {thread.id}): {e}")

    # -------------------------
    # 转段确认消息
    # -------------------------

    async def send_transition_confirmation_message(
        self,
        thread: discord.Thread,
        session_dto: "ConfirmationSessionDto",
        guild_id: int,
    ) -> None:
        """在审核帖发送转段确认消息。"""
        if not self.bot.user:
            return

        roles_config = self.bot.config.get("roles", {})
        guild = self.bot.get_guild(guild_id)
        role_display_names = {}
        for role_key in session_dto.required_roles:
            role_id = roles_config.get(role_key)
            if role_id and guild:
                role = guild.get_role(int(role_id))
                base_name = role.name if role else role_key
            else:
                base_name = role_key
            display_name = base_name
            counter = 2
            while display_name in role_display_names.values():
                display_name = f"{base_name} {counter}"
                counter += 1
            role_display_names[role_key] = display_name

        qo = BuildConfirmationEmbedQo(
            context=session_dto.context,
            status=session_dto.status,
            canceler_id=session_dto.canceler_id,
            confirmed_parties=session_dto.confirmed_parties,
            required_roles=session_dto.required_roles,
            role_display_names=role_display_names,
        )
        embed = ModerationEmbedBuilder.build_confirmation_embed(qo, self.bot.user)
        view = ConfirmationView(self.bot, hide_cancel=True)

        pings = []
        moderator_role_id = roles_config.get("councilModerator")
        auditor_role_id = roles_config.get("executionAuditor")
        if moderator_role_id:
            pings.append(f"<@&{moderator_role_id}>")
        if auditor_role_id and auditor_role_id != moderator_role_id:
            pings.append(f"<@&{auditor_role_id}>")
        content = " ".join(pings) if pings else None

        message = await thread.send(content=content, embed=embed, view=view)

        async with UnitOfWork(self.bot.db_handler) as uow:
            await uow.confirmation_session.update_confirmation_session_message_id(
                session_dto.id, message.id
            )
            await uow.commit()
