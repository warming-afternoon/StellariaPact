import asyncio
import logging
from collections.abc import Sequence

import discord
from discord import app_commands
from discord.ext import commands

from StellariaPact.cogs.Voting.views import VoteEmbedBuilder
from StellariaPact.dto.vote_session import VoteDetailDto
from StellariaPact.qo.structured_speech import (
    DeleteStructuredSpeechMessagesQo, DisableStructuredSpeechModeQo,
    EnableStructuredSpeechModeQo, PublishStructuredSpeechQo,
    ResolveStructuredSpeechReferenceQo)
from StellariaPact.share import (DiscordUtils, RoleGuard, StellariaPactBot,
                                 safeDefer)

from .constants import (GOVERNANCE_ROLE_KEYS,
                        STRUCTURED_SPEECH_MAX_INTERVAL_MINUTES,
                        STRUCTURED_SPEECH_MESSAGE_MAX_LENGTH,
                        STRUCTURED_SPEECH_MIN_INTERVAL_MINUTES,
                        STRUCTURED_SPEECH_REPLY_CONTEXT_MENU_NAME)
from .ProposalSpeechModal import ProposalSpeechModal
from .StructuredSpeechService import StructuredSpeechService
from .StructuredSpeechUserError import StructuredSpeechUserError

logger = logging.getLogger(__name__)


class StructuredSpeechCog(commands.Cog):
    """处理提案结构化发言命令与消息生命周期事件。"""

    def __init__(self, bot: StellariaPactBot):
        """初始化控制器及其业务服务。"""
        self.bot = bot
        self.service = StructuredSpeechService(bot)
        self.proposal_speech_reply_context_menu = app_commands.ContextMenu(
            name=STRUCTURED_SPEECH_REPLY_CONTEXT_MENU_NAME,
            callback=self.proposal_speech_reply,
            type=discord.AppCommandType.message,
        )

    def cog_load(self) -> None:
        """注册结构化发言的消息右键应用指令。"""
        self.bot.tree.add_command(self.proposal_speech_reply_context_menu)

    async def cog_unload(self) -> None:
        """卸载结构化发言的消息右键应用指令。"""
        self.bot.tree.remove_command(
            self.proposal_speech_reply_context_menu.name,
            type=self.proposal_speech_reply_context_menu.type,
        )

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """在 Bot 就绪后加载模式，并恢复未完成的切换。"""
        await self.service.load_and_recover()

    def is_structured_webhook_id(self, user_id: int) -> bool:
        """供远端消息事件入口判断并跳过结构化 Webhook 作者。"""
        return self.service.is_structured_webhook_id(user_id)

    @app_commands.command(
        name="模板发言模式",
        description="开启或关闭当前提案帖子的结构化发言模式",
    )
    @app_commands.rename(state="状态", interval_minutes="发言间隔分钟")
    @app_commands.describe(
        state="明确选择开启或关闭",
        interval_minutes="每位用户在本帖通过 Bot 发言的间隔，默认 2 分钟",
    )
    @app_commands.choices(
        state=[
            app_commands.Choice(name="开启", value="enable"),
            app_commands.Choice(name="关闭", value="disable"),
        ]
    )
    @app_commands.guild_only()
    @RoleGuard.requireRoles(*GOVERNANCE_ROLE_KEYS)
    async def template_speech_mode(
        self,
        interaction: discord.Interaction,
        state: app_commands.Choice[str],
        interval_minutes: app_commands.Range[
            int,
            STRUCTURED_SPEECH_MIN_INTERVAL_MINUTES,
            STRUCTURED_SPEECH_MAX_INTERVAL_MINUTES,
        ]
        | None = None,
    ) -> None:
        """开启、更新或关闭当前帖子的模板发言模式。"""
        await safeDefer(interaction, ephemeral=True)
        try:
            # 控制器先校验命令上下文与 Bot 的实际频道权限。
            thread = self._get_target_thread(interaction)
            member = await self._get_bot_member(interaction)

            if state.value == "enable":
                missing = self.get_missing_enable_permissions(thread, member)
                if missing:
                    formatted = "\n".join(f"- {name}" for name in missing)
                    raise StructuredSpeechUserError(
                        f"无法开启模板发言模式，Bot 缺少以下权限：\n{formatted}"
                    )
                parent = thread.parent
                assert isinstance(parent, discord.ForumChannel)
                await self.service.ensure_webhook(parent)
                result = await self.service.enable_mode(
                    thread=thread,
                    qo=EnableStructuredSpeechModeQo(
                        operator_id=interaction.user.id,
                        interval_seconds=(interval_minutes * 60 if interval_minutes else None),
                    ),
                )
                mode = self.service.get_active_mode(thread.id)
                assert mode is not None
                minutes = mode.interval_seconds // 60
                if result.action == "enabled":
                    announced = await self._send_public_announcement(
                        thread,
                        f"📋 模板发言模式已由 {interaction.user.mention} 开启。"
                        f"请使用 `/提案发言`，每人每 {minutes} 分钟可发送一次。",
                    )
                    response = "模板发言模式已开启。"
                    if not announced:
                        response += "但公开公告发送失败，请检查频道状态。"
                elif result.action == "updated":
                    announced = await self._send_public_announcement(
                        thread,
                        f"⏱️ 模板发言间隔已由 {interaction.user.mention} 调整为 {minutes} 分钟。",
                    )
                    response = "模板发言间隔已更新。"
                    if not announced:
                        response += "但公开公告发送失败，请检查频道状态。"
                else:
                    response = f"模板发言模式已经开启，当前间隔为 {minutes} 分钟。"
            else:
                if interval_minutes is not None:
                    raise StructuredSpeechUserError("关闭模式时无需填写发言间隔。")
                if self.service.get_active_mode(thread.id) is None:
                    response = "当前帖子未开启模板发言模式。"
                else:
                    missing = self.get_missing_disable_permissions(thread, member)
                    if missing:
                        formatted = "\n".join(f"- {name}" for name in missing)
                        raise StructuredSpeechUserError(
                            f"无法关闭模板发言模式，Bot 缺少以下权限：\n{formatted}"
                        )
                    result = await self.service.disable_mode(
                        thread,
                        DisableStructuredSpeechModeQo(operator_id=interaction.user.id),
                    )
                    if result.action == "disabled":
                        announced = await self._send_public_announcement(
                            thread,
                            f"📭 模板发言模式已由 {interaction.user.mention} 关闭，"
                            "帖子慢速模式已恢复。",
                        )
                        response = "模板发言模式已关闭。"
                        if not announced:
                            response += "但公开公告发送失败，请检查频道状态。"
                    else:
                        response = "当前帖子未开启模板发言模式。"
            await interaction.followup.send(response, ephemeral=True)
        except StructuredSpeechUserError as error:
            await interaction.followup.send(str(error), ephemeral=True)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            logger.exception("Discord 拒绝了模板发言模式变更。")
            await interaction.followup.send(
                "Discord 拒绝了模式变更，请检查 Bot 权限后重试。",
                ephemeral=True,
            )
        except Exception:
            logger.exception("切换模板发言模式失败。")
            await interaction.followup.send("切换模板发言模式失败，请稍后重试。", ephemeral=True)

    @app_commands.command(name="提案发言", description="使用结构化模板在当前提案帖子中发言")
    @app_commands.guild_only()
    async def proposal_speech(self, interaction: discord.Interaction) -> None:
        """预检当前发言资格并打开结构化发言表单。"""
        try:
            # 表单打开前先做轻量预检，避免用户填写后才发现不可发送。
            thread = self._get_target_thread(interaction)
            member = self._get_interaction_member(interaction)
            await self._validate_speech_preflight(thread, member)
            await interaction.response.send_modal(
                ProposalSpeechModal(self, thread_id=thread.id, user_id=member.id)
            )
        except StructuredSpeechUserError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
        except Exception:
            logger.exception("打开提案发言表单失败。")
            await interaction.response.send_message(
                "无法打开提案发言表单，请稍后重试。",
                ephemeral=True,
            )

    async def proposal_speech_reply(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
    ) -> None:
        """从消息右键入口打开自动关联原发言者的结构化发言表单。"""
        try:
            # 右键入口沿用斜杠指令的帖子、处罚和冷却预检。
            thread = self._get_target_thread(interaction)
            member = self._get_interaction_member(interaction)
            await self._validate_speech_preflight(thread, member)

            # 仅在打开表单时解析一次目标身份，提交时不再读取源消息。
            reference_user_id = await self.service.resolve_reference_user_id(
                ResolveStructuredSpeechReferenceQo(
                    message_id=message.id,
                    author_id=message.author.id,
                    author_is_bot=message.author.bot,
                    webhook_id=message.webhook_id,
                )
            )
            await interaction.response.send_modal(
                ProposalSpeechModal(
                    self,
                    thread_id=thread.id,
                    user_id=member.id,
                    reference_message_url=message.jump_url,
                    reference_user_id=reference_user_id,
                )
            )
        except StructuredSpeechUserError as error:
            await interaction.response.send_message(str(error), ephemeral=True)
        except Exception:
            logger.exception("打开提案回复发言表单失败。")
            await interaction.response.send_message(
                "无法打开提案回复发言表单，请稍后重试。",
                ephemeral=True,
            )

    @staticmethod
    def format_proposal_speech_content(
        *,
        body: str,
        reason: str,
        reference_message_url: str | None = None,
        reference_user_id: int | None = None,
    ) -> str:
        """清理并格式化普通发言或带模拟引用的提案发言内容。"""
        # 正文和理由去除首尾空白后必须仍有实际内容。
        body = body.strip()
        reason = reason.strip()
        if not body or not reason:
            raise StructuredSpeechUserError("正文和理由都不能为空。")
        if (reference_message_url is None) != (reference_user_id is None):
            raise StructuredSpeechUserError("回复引用信息不完整，请重新打开提案发言表单。")

        # 右键回复固定使用源消息链接和真实用户提及作为前两行。
        reference_prefix = ""
        if reference_message_url is not None and reference_user_id is not None:
            reference_prefix = f"-# 回复 <@{reference_user_id}> 的 [发言]({reference_message_url})\n"
        content = f"{reference_prefix}-# 正文\n{body}\n\n-# 理由\n{reason}"
        if len(content) > STRUCTURED_SPEECH_MESSAGE_MAX_LENGTH:
            raise StructuredSpeechUserError(
                f"格式化后的消息共有 {len(content)} 个字符，最多允许 "
                f"{STRUCTURED_SPEECH_MESSAGE_MAX_LENGTH} 个字符。"
            )
        return content

    async def submit_proposal_speech(
        self,
        interaction: discord.Interaction,
        *,
        expected_thread_id: int,
        expected_user_id: int,
        body: str,
        reason: str,
        attachments: Sequence[discord.Attachment],
        reference_message_url: str | None = None,
        reference_user_id: int | None = None,
    ) -> None:
        """处理表单提交并发送结构化 Webhook 消息。"""
        await safeDefer(interaction, ephemeral=True)
        try:
            # 提交时重新解析并核对用户与帖子，拒绝过期或错位的表单。
            thread = self._get_target_thread(interaction)
            member = self._get_interaction_member(interaction)
            if thread.id != expected_thread_id or member.id != expected_user_id:
                raise StructuredSpeechUserError("表单上下文已失效，请重新执行 `/提案发言`。")

            # 使用表单打开时保存的引用上下文，不重新读取或确认源消息。
            content = self.format_proposal_speech_content(
                body=body,
                reason=reason,
                reference_message_url=reference_message_url,
                reference_user_id=reference_user_id,
            )

            sent = await self.service.publish(
                thread=thread,
                member=member,
                qo=PublishStructuredSpeechQo(
                    guild_id=thread.guild.id,
                    thread_id=thread.id,
                    user_id=member.id,
                    content=content,
                    cooldown_exempt=self._is_governance_member(member),
                ),
                attachments=attachments,
            )
            await interaction.followup.send(
                f"提案发言已发送：[查看消息]({sent.jump_url})",
                ephemeral=True,
            )
        except StructuredSpeechUserError as error:
            await interaction.followup.send(str(error), ephemeral=True)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            logger.exception("Discord 拒绝了结构化提案发言。")
            await interaction.followup.send(
                "消息或附件发送失败，请检查 Bot 权限和文件大小后重试。",
                ephemeral=True,
            )
        except Exception:
            logger.exception("提交结构化提案发言失败。")
            await interaction.followup.send("提案发言发送失败，请稍后重试。", ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """删除活动模式中普通成员绕过 Bot 直接发送的消息。"""
        # Bot、Webhook、治理角色及非目标帖子不受直接发言拦截。
        if (
            message.author.bot
            or message.webhook_id is not None
            or not isinstance(message.channel, discord.Thread)
            or self.service.get_active_mode(message.channel.id) is None
            or not self._is_target_thread(message.channel)
        ):
            return
        if isinstance(message.author, discord.Member) and self._is_governance_member(
            message.author
        ):
            return
        try:
            await self.bot.api_scheduler.submit(message.delete(), priority=1)
        except discord.NotFound:
            pass
        except discord.Forbidden:
            logger.warning(
                "无法删除模板发言帖子 %s 中绕过 Bot 的消息 %s。",
                message.channel.id,
                message.id,
            )
        except discord.HTTPException:
            logger.exception(
                "删除模板发言帖子 %s 中绕过 Bot 的消息 %s 失败。",
                message.channel.id,
                message.id,
            )

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        """处理单条结构化消息的原始删除事件。"""
        await self._handle_deleted_ids((payload.message_id,))

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(
        self,
        payload: discord.RawBulkMessageDeleteEvent,
    ) -> None:
        """处理批量结构化消息的原始删除事件。"""
        await self._handle_deleted_ids(payload.message_ids)

    async def _handle_deleted_ids(self, message_ids: Sequence[int] | set[int]) -> None:
        """回滚已删除消息，并并发刷新受影响的投票面板。"""
        try:
            updates = await self.service.handle_message_deletions(
                DeleteStructuredSpeechMessagesQo(message_ids=set(message_ids))
            )
            await asyncio.gather(
                *(
                    self._refresh_vote_panels(update.thread_id, update.vote_details)
                    for update in updates
                )
            )
        except Exception:
            logger.exception("处理结构化消息删除事件失败。")

    async def _refresh_vote_panels(
        self,
        thread_id: int,
        details_list: list[VoteDetailDto],
    ) -> None:
        """并发刷新指定帖子中受资格变化影响的投票面板。"""
        thread = await DiscordUtils.fetch_thread(self.bot, thread_id)
        if thread is None:
            return
        await asyncio.gather(
            *(self._refresh_vote_panel(thread, details) for details in details_list),
            return_exceptions=True,
        )

    async def _refresh_vote_panel(
        self,
        thread: discord.Thread,
        details: VoteDetailDto,
    ) -> None:
        """刷新一个投票面板消息。"""
        if not details.context_message_id:
            return
        try:
            message = await thread.fetch_message(details.context_message_id)
            embeds = VoteEmbedBuilder.create_vote_panel_embed_v2(
                topic=thread.name,
                vote_details=details,
            )
            await self.bot.api_scheduler.submit(message.edit(embeds=embeds), priority=2)
        except (discord.Forbidden, discord.NotFound, IndexError):
            logger.warning(
                "无法刷新帖子 %s 中的投票面板 %s。",
                thread.id,
                details.context_message_id,
            )

    async def _validate_speech_preflight(
        self,
        thread: discord.Thread,
        member: discord.Member,
    ) -> None:
        """在打开 Modal 前检查模式、处罚和用户冷却。"""
        if self.service.get_active_mode(thread.id) is None:
            raise StructuredSpeechUserError("当前帖子未开启模板发言模式。")
        if await self.service.is_user_punished(thread_id=thread.id, user_id=member.id):
            raise StructuredSpeechUserError("你当前受到提案发言处罚，无法发送消息。")
        if not self._is_governance_member(member):
            remaining = await self.service.get_cooldown_remaining(
                thread_id=thread.id,
                user_id=member.id,
            )
            if remaining > 0:
                raise StructuredSpeechUserError(f"发言冷却中，请在 {remaining} 秒后重试。")

    def _get_target_thread(self, interaction: discord.Interaction) -> discord.Thread:
        """从交互中取得配置论坛下的目标帖子。"""
        channel = interaction.channel
        if not isinstance(channel, discord.Thread) or not self._is_target_thread(channel):
            raise StructuredSpeechUserError("此命令只能在提案讨论论坛的帖子中使用。")
        return channel

    def _is_target_thread(self, thread: discord.Thread) -> bool:
        """判断帖子是否属于配置的提案讨论论坛。"""
        configured = self.bot.config.get("channels", {}).get("discussion")
        try:
            return thread.parent_id == int(configured)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _get_interaction_member(interaction: discord.Interaction) -> discord.Member:
        """从服务器交互中取得成员对象。"""
        if not isinstance(interaction.user, discord.Member):
            raise StructuredSpeechUserError("此命令只能由服务器成员使用。")
        return interaction.user

    async def _get_bot_member(self, interaction: discord.Interaction) -> discord.Member:
        """取得用于计算实际频道权限的 Bot 成员对象。"""
        guild = interaction.guild
        if guild is None or self.bot.user is None:
            raise StructuredSpeechUserError("无法解析 Bot 的服务器权限。")
        member = guild.me or guild.get_member(self.bot.user.id)
        if member is None:
            member = await self.bot.api_scheduler.submit(
                guild.fetch_member(self.bot.user.id),
                priority=1,
            )
        return member

    def _is_governance_member(self, member: discord.Member) -> bool:
        """判断成员是否拥有任一配置的治理角色。"""
        configured_roles = self.bot.config.get("roles", {})
        allowed_ids: set[int] = set()
        for key in GOVERNANCE_ROLE_KEYS:
            raw_id = configured_roles.get(key)
            try:
                if raw_id:
                    allowed_ids.add(int(raw_id))
            except (TypeError, ValueError):
                continue
        return any(role.id in allowed_ids for role in member.roles)

    @staticmethod
    def get_missing_enable_permissions(
        thread: discord.Thread,
        member: discord.Member,
    ) -> list[str]:
        """列出开启模式所缺少的帖子或父论坛权限。"""
        parent = thread.parent
        if not isinstance(parent, discord.ForumChannel):
            return ["访问父论坛"]
        thread_permissions = thread.permissions_for(member)
        forum_permissions = parent.permissions_for(member)
        required = {
            "查看帖子": thread_permissions.view_channel,
            "在线程中发言": thread_permissions.send_messages_in_threads,
            "管理消息": thread_permissions.manage_messages,
            "管理线程": thread_permissions.manage_threads,
            "上传附件": thread_permissions.attach_files,
            "读取消息历史": thread_permissions.read_message_history,
            "管理 Webhook": forum_permissions.manage_webhooks,
        }
        return [name for name, allowed in required.items() if not allowed]

    @staticmethod
    def get_missing_disable_permissions(
        thread: discord.Thread,
        member: discord.Member,
    ) -> list[str]:
        """列出关闭模式并恢复慢速值所缺少的权限。"""
        permissions = thread.permissions_for(member)
        required = {
            "查看帖子": permissions.view_channel,
            "在线程中发言": permissions.send_messages_in_threads,
            "管理线程": permissions.manage_threads,
        }
        return [name for name, allowed in required.items() if not allowed]

    async def _send_public_announcement(self, thread: discord.Thread, content: str) -> bool:
        """在帖子内发送允许用户提及的公开状态公告。"""
        try:
            await self.bot.api_scheduler.submit(
                thread.send(
                    content,
                    allowed_mentions=discord.AllowedMentions(
                        everyone=False,
                        users=True,
                        roles=False,
                        replied_user=True,
                    ),
                ),
                priority=1,
            )
            return True
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            logger.exception("帖子 %s 的模板发言状态公告发送失败。", thread.id)
            return False
