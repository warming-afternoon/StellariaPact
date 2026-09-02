from __future__ import annotations

import asyncio
import logging
import math
from collections import Counter
from datetime import datetime, timezone
from typing import Sequence

import discord

from StellariaPact.cogs.Voting.EligibilityService import EligibilityService
from StellariaPact.cogs.Voting.VotingLogic import VotingLogic
from StellariaPact.dto import UserActivityDto
from StellariaPact.dto.structured_speech import (
    ModeChangeResultDto,
    StructuredSpeechDeletionResultDto,
    StructuredSpeechModeDto,
)
from StellariaPact.models.StructuredSpeechMode import StructuredSpeechMode
from StellariaPact.qo.structured_speech import (
    DeleteStructuredSpeechMessagesQo,
    DisableStructuredSpeechModeQo,
    EnableStructuredSpeechModeQo,
    PublishStructuredSpeechQo,
    ResolveStructuredSpeechReferenceQo,
)
from StellariaPact.qo.user_activity import UpdateUserActivityQo
from StellariaPact.share import DiscordUtils, StellariaPactBot, UnitOfWork

from .constants import (
    STRUCTURED_SPEECH_DEFAULT_INTERVAL_SECONDS,
    STRUCTURED_SPEECH_MAX_ATTACHMENTS,
    STRUCTURED_SPEECH_SLOWMODE_SECONDS,
    STRUCTURED_SPEECH_STATUS_ACTIVE,
    STRUCTURED_SPEECH_STATUS_DISABLING,
    STRUCTURED_SPEECH_STATUS_ENABLING,
    STRUCTURED_SPEECH_STATUS_INACTIVE,
    STRUCTURED_SPEECH_WEBHOOK_NAME,
)
from .StructuredSpeechMessageTargetResolver import StructuredSpeechMessageTargetResolver
from .StructuredSpeechUserError import StructuredSpeechUserError

logger = logging.getLogger(__name__)


class StructuredSpeechService:
    """协调模板发言状态、Webhook、冷却和活动计数。"""

    def __init__(self, bot: StellariaPactBot):
        """初始化服务及单进程并发锁。"""
        self.bot = bot
        self.active_modes: dict[int, StructuredSpeechModeDto] = {}
        self._mode_locks: dict[int, asyncio.Lock] = {}
        self._user_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._webhooks: dict[int, discord.Webhook] = {}
        self._structured_webhook_ids: set[int] = set()
        self._webhook_lock = asyncio.Lock()
        self._deletion_lock = asyncio.Lock()
        self._load_lock = asyncio.Lock()
        self._loaded = False
        self.message_target_resolver = StructuredSpeechMessageTargetResolver(bot)

    def mode_lock(self, thread_id: int) -> asyncio.Lock:
        """取得指定帖子的模式切换锁。"""
        return self._mode_locks.setdefault(thread_id, asyncio.Lock())

    def user_lock(self, thread_id: int, user_id: int) -> asyncio.Lock:
        """取得指定用户在指定帖子中的发言锁。"""
        return self._user_locks.setdefault((thread_id, user_id), asyncio.Lock())

    def get_active_mode(self, thread_id: int) -> StructuredSpeechModeDto | None:
        """读取指定帖子的活动模式快照。"""
        return self.active_modes.get(thread_id)

    def is_structured_webhook_id(self, user_id: int) -> bool:
        """判断远端消息事件作者是否为结构化发言 Webhook。"""
        return user_id in self._structured_webhook_ids

    async def load_and_recover(self) -> None:
        """加载活动模式，并仅恢复未完成的状态切换。"""
        async with self._load_lock:
            if self._loaded:
                return

            recovery_failed = False

            # 一次性读取所需字段，避免 ORM 对象离开会话后继续传播。
            async with UnitOfWork(self.bot.db_handler) as uow:
                modes = await uow.structured_speech_mode.get_by_statuses(
                    STRUCTURED_SPEECH_STATUS_ACTIVE,
                    STRUCTURED_SPEECH_STATUS_ENABLING,
                    STRUCTURED_SPEECH_STATUS_DISABLING,
                )
                records = [
                    (
                        mode.thread_id,
                        mode.forum_id,
                        mode.status,
                        mode.interval_seconds,
                        mode.proposer_cooldown_exempt,
                        mode.previous_slowmode_delay,
                    )
                    for mode in modes
                ]
                webhook_ids = await uow.structured_speech_message.get_webhook_ids()

            # 启动时一次加载 Webhook ID，远端事件入口无需逐消息查询数据库。
            self._structured_webhook_ids.update(webhook_ids)

            for (
                thread_id,
                forum_id,
                status,
                interval,
                proposer_cooldown_exempt,
                previous_slowmode,
            ) in records:
                if status == STRUCTURED_SPEECH_STATUS_ACTIVE:
                    self.active_modes[thread_id] = StructuredSpeechModeDto(
                        thread_id=thread_id,
                        forum_id=forum_id,
                        interval_seconds=interval,
                        proposer_cooldown_exempt=proposer_cooldown_exempt,
                        previous_slowmode_delay=previous_slowmode,
                    )
                    continue
                try:
                    thread = await DiscordUtils.fetch_thread(self.bot, thread_id)
                    if thread is None:
                        logger.warning(
                            "无法恢复帖子 %s 的模板发言过渡状态：帖子不存在。",
                            thread_id,
                        )
                        continue
                    if status == STRUCTURED_SPEECH_STATUS_ENABLING:
                        # 仅过渡态会在重启时继续写入慢速模式，活动态不会被纠正。
                        await self._edit_slowmode(thread, STRUCTURED_SPEECH_SLOWMODE_SECONDS)
                        await self._set_mode_status(thread_id, STRUCTURED_SPEECH_STATUS_ACTIVE)
                        self.active_modes[thread_id] = StructuredSpeechModeDto(
                            thread_id=thread_id,
                            forum_id=forum_id,
                            interval_seconds=interval,
                            proposer_cooldown_exempt=proposer_cooldown_exempt,
                            previous_slowmode_delay=previous_slowmode,
                        )
                    elif status == STRUCTURED_SPEECH_STATUS_DISABLING:
                        await self._edit_slowmode(thread, previous_slowmode)
                        await self._set_mode_status(thread_id, STRUCTURED_SPEECH_STATUS_INACTIVE)
                        self.active_modes.pop(thread_id, None)
                except Exception:
                    recovery_failed = True
                    logger.exception(
                        "恢复帖子 %s 的模板发言过渡状态失败。",
                        thread_id,
                    )

            self._loaded = not recovery_failed
            logger.info("已加载 %s 个活动模板发言模式。", len(self.active_modes))

    async def enable_mode(
        self,
        *,
        thread: discord.Thread,
        qo: EnableStructuredSpeechModeQo,
    ) -> ModeChangeResultDto:
        """开启模板发言模式，或更新已开启模式的冷却。"""
        parent = thread.parent
        if not isinstance(parent, discord.ForumChannel):
            raise StructuredSpeechUserError("当前帖子不属于论坛频道。")

        # 模式切换与发言共用帖子锁，避免关闭和发送同时发生。
        async with self.mode_lock(thread.id):
            async with UnitOfWork(self.bot.db_handler) as uow:
                mode = await uow.structured_speech_mode.get(thread.id)
                if mode is not None and mode.status == STRUCTURED_SPEECH_STATUS_ACTIVE:
                    new_interval = (
                        qo.interval_seconds
                        if qo.interval_seconds is not None
                        else mode.interval_seconds
                    )
                    new_proposer_exemption = (
                        qo.proposer_cooldown_exempt
                        if qo.proposer_cooldown_exempt is not None
                        else mode.proposer_cooldown_exempt
                    )
                    if (
                        new_interval == mode.interval_seconds
                        and new_proposer_exemption == mode.proposer_cooldown_exempt
                    ):
                        self.active_modes[thread.id] = self._snapshot(mode)
                        return ModeChangeResultDto(
                            action="unchanged",
                            interval_seconds=mode.interval_seconds,
                            proposer_cooldown_exempt=mode.proposer_cooldown_exempt,
                        )
                    mode.interval_seconds = new_interval
                    mode.proposer_cooldown_exempt = new_proposer_exemption
                    mode.enabled_by_id = qo.operator_id
                    mode.updated_at = datetime.now(timezone.utc)
                    await uow.structured_speech_mode.save(mode)
                    self.active_modes[thread.id] = self._snapshot(mode)
                    return ModeChangeResultDto(
                        action="updated",
                        interval_seconds=new_interval,
                        proposer_cooldown_exempt=new_proposer_exemption,
                    )

                selected_interval = (
                    qo.interval_seconds or STRUCTURED_SPEECH_DEFAULT_INTERVAL_SECONDS
                )
                selected_proposer_exemption = (
                    qo.proposer_cooldown_exempt
                    if qo.proposer_cooldown_exempt is not None
                    else True
                )
                previous_slowmode = thread.slowmode_delay
                if mode is None:
                    mode = StructuredSpeechMode(
                        guild_id=thread.guild.id,
                        forum_id=parent.id,
                        thread_id=thread.id,
                        status=STRUCTURED_SPEECH_STATUS_ENABLING,
                        interval_seconds=selected_interval,
                        proposer_cooldown_exempt=selected_proposer_exemption,
                        previous_slowmode_delay=previous_slowmode,
                        enabled_by_id=qo.operator_id,
                    )
                else:
                    mode.guild_id = thread.guild.id
                    mode.forum_id = parent.id
                    mode.status = STRUCTURED_SPEECH_STATUS_ENABLING
                    mode.interval_seconds = selected_interval
                    mode.proposer_cooldown_exempt = selected_proposer_exemption
                    mode.previous_slowmode_delay = previous_slowmode
                    mode.enabled_by_id = qo.operator_id
                    mode.updated_at = datetime.now(timezone.utc)
                await uow.structured_speech_mode.save(mode)
                await uow.commit()

            # 数据库先记录过渡态，Discord 成功后再标记为活动态。
            try:
                await self._edit_slowmode(thread, STRUCTURED_SPEECH_SLOWMODE_SECONDS)
            except Exception:
                await self._set_mode_status(thread.id, STRUCTURED_SPEECH_STATUS_INACTIVE)
                raise

            await self._set_mode_status(thread.id, STRUCTURED_SPEECH_STATUS_ACTIVE)
            self.active_modes[thread.id] = StructuredSpeechModeDto(
                thread_id=thread.id,
                forum_id=parent.id,
                interval_seconds=selected_interval,
                proposer_cooldown_exempt=selected_proposer_exemption,
                previous_slowmode_delay=previous_slowmode,
            )
            return ModeChangeResultDto(
                action="enabled",
                interval_seconds=selected_interval,
                proposer_cooldown_exempt=selected_proposer_exemption,
            )

    async def disable_mode(
        self,
        thread: discord.Thread,
        qo: DisableStructuredSpeechModeQo,
    ) -> ModeChangeResultDto:
        """关闭模式并始终恢复开启前保存的慢速值。"""
        async with self.mode_lock(thread.id):
            async with UnitOfWork(self.bot.db_handler) as uow:
                mode = await uow.structured_speech_mode.get(thread.id)
                if mode is None or mode.status == STRUCTURED_SPEECH_STATUS_INACTIVE:
                    self.active_modes.pop(thread.id, None)
                    return ModeChangeResultDto(action="unchanged")
                previous_slowmode = mode.previous_slowmode_delay
                mode.status = STRUCTURED_SPEECH_STATUS_DISABLING
                mode.enabled_by_id = qo.operator_id
                mode.updated_at = datetime.now(timezone.utc)
                await uow.structured_speech_mode.save(mode)
                await uow.commit()

            # 即使活动期间被人工修改，关闭时仍以保存的原值为准。
            try:
                await self._edit_slowmode(thread, previous_slowmode)
            except Exception:
                await self._set_mode_status(thread.id, STRUCTURED_SPEECH_STATUS_ACTIVE)
                raise

            await self._set_mode_status(thread.id, STRUCTURED_SPEECH_STATUS_INACTIVE)
            self.active_modes.pop(thread.id, None)
            return ModeChangeResultDto(action="disabled")

    async def ensure_webhook(self, forum: discord.ForumChannel) -> discord.Webhook:
        """查找或创建当前 Bot 在父论坛中的专用 Webhook。"""
        # 优先使用本进程缓存，减少论坛 Webhook 列表请求。
        cached = self._webhooks.get(forum.id)
        if cached is not None:
            return cached

        async with self._webhook_lock:
            cached = self._webhooks.get(forum.id)
            if cached is not None:
                return cached
            webhooks = await self.bot.api_scheduler.submit(forum.webhooks(), priority=2)
            bot_user_id = self.bot.user.id if self.bot.user else None
            # 只复用当前 Bot 创建且仍带令牌的同名 Webhook。
            webhook = next(
                (
                    candidate
                    for candidate in webhooks
                    if candidate.name == STRUCTURED_SPEECH_WEBHOOK_NAME
                    and candidate.user is not None
                    and candidate.user.id == bot_user_id
                    and candidate.token is not None
                ),
                None,
            )
            if webhook is None:
                webhook = await self.bot.api_scheduler.submit(
                    forum.create_webhook(
                        name=STRUCTURED_SPEECH_WEBHOOK_NAME,
                        reason="用于提案讨论的结构化发言",
                    ),
                    priority=2,
                )
            self._webhooks[forum.id] = webhook
            self._structured_webhook_ids.add(webhook.id)
            return webhook

    async def get_cooldown_remaining(self, *, thread_id: int, user_id: int) -> int:
        """计算用户在帖子中的剩余 Bot 发言冷却秒数。"""
        mode = self.active_modes.get(thread_id)
        if mode is None:
            return 0
        # 冷却以最近一次成功持久化的结构化发言为准，删除消息不会重置冷却。
        async with UnitOfWork(self.bot.db_handler) as uow:
            last_message = await uow.structured_speech_message.get_last(
                thread_id=thread_id,
                user_id=user_id,
            )
            if last_message is None:
                return 0
            created_at = last_message.created_at
        elapsed = (datetime.now(timezone.utc) - created_at).total_seconds()
        return max(0, math.ceil(mode.interval_seconds - elapsed))

    async def is_cooldown_exempt(
        self,
        *,
        thread_id: int,
        user_id: int,
        always_exempt: bool,
    ) -> bool:
        """判断治理角色或当前模式配置允许的提案主是否豁免冷却。"""
        if always_exempt:
            return True
        mode = self.active_modes.get(thread_id)
        if mode is None or not mode.proposer_cooldown_exempt:
            return False
        async with UnitOfWork(self.bot.db_handler) as uow:
            proposal = await uow.proposal.get_proposal_by_thread_id(thread_id)
            return proposal is not None and proposal.proposer_id == user_id

    async def is_user_punished(self, *, thread_id: int, user_id: int) -> bool:
        """按现有帖子禁言和全局提案处罚规则判断用户是否可发言。"""
        now = datetime.now(timezone.utc)
        # 在一个工作单元中读取帖子活动、提案和全局处罚，避免跨会话对象传播。
        async with UnitOfWork(self.bot.db_handler) as uow:
            activity = await uow.user_activity.get_user_activity(user_id, thread_id)
            if activity and activity.mute_end_time and activity.mute_end_time > now:
                return True
            return await uow.global_proposal_punishment.is_proposal_violation_restricted(user_id)

    async def resolve_reference_user_id(
        self,
        qo: ResolveStructuredSpeechReferenceQo,
    ) -> int:
        """解析普通成员或结构化 Webhook 消息对应的真实用户 ID。"""
        return await self.message_target_resolver.resolve_user_id(qo)

    async def publish(
        self,
        *,
        thread: discord.Thread,
        member: discord.Member,
        qo: PublishStructuredSpeechQo,
        attachments: Sequence[discord.Attachment],
    ) -> discord.WebhookMessage:
        """校验并发送一次结构化发言，同时原子记录活动计数。"""
        if len(attachments) > STRUCTURED_SPEECH_MAX_ATTACHMENTS:
            raise StructuredSpeechUserError("每次最多只能上传 5 个附件。")

        # 锁内重新检查模式、处罚和冷却，防止并发提交绕过限制。
        async with self.mode_lock(thread.id):
            async with self.user_lock(thread.id, member.id):
                mode = self.active_modes.get(thread.id)
                if mode is None:
                    raise StructuredSpeechUserError("当前帖子未开启模板发言模式。")
                if qo.thread_id != thread.id or qo.user_id != member.id:
                    raise StructuredSpeechUserError("发言上下文不一致，请重新执行命令。")
                if await self.is_user_punished(thread_id=qo.thread_id, user_id=qo.user_id):
                    raise StructuredSpeechUserError("你当前受到提案发言处罚，无法发送消息。")
                if not await self.is_cooldown_exempt(
                    thread_id=qo.thread_id,
                    user_id=qo.user_id,
                    always_exempt=qo.cooldown_exempt,
                ):
                    remaining = await self.get_cooldown_remaining(
                        thread_id=qo.thread_id,
                        user_id=qo.user_id,
                    )
                    if remaining > 0:
                        raise StructuredSpeechUserError(f"发言冷却中，请在 {remaining} 秒后重试。")

                parent = thread.parent
                if not isinstance(parent, discord.ForumChannel):
                    raise StructuredSpeechUserError("当前帖子不属于论坛频道。")
                webhook = await self.ensure_webhook(parent)

                # 先完整下载全部附件，任一失败都不会产生部分 Webhook 消息。
                file_results = await asyncio.gather(
                    *(item.to_file() for item in attachments),
                    return_exceptions=True,
                )
                files = [item for item in file_results if isinstance(item, discord.File)]
                file_errors = [item for item in file_results if isinstance(item, BaseException)]
                if file_errors:
                    for file in files:
                        file.close()
                    raise file_errors[0]
                try:
                    kwargs = {
                        "username": member.display_name,
                        "avatar_url": member.display_avatar.url,
                        "allowed_mentions": discord.AllowedMentions(
                            everyone=False,
                            users=True,
                            roles=False,
                            replied_user=True,
                        ),
                        "thread": thread,
                        "wait": True,
                    }
                    if files:
                        kwargs["files"] = files
                    sent = await self.bot.api_scheduler.submit(
                        webhook.send(qo.content, **kwargs),  # type: ignore[arg-type]
                        priority=1,
                    )
                finally:
                    for file in files:
                        file.close()

                if not isinstance(sent, discord.WebhookMessage):
                    raise RuntimeError("Webhook 未返回已创建的消息。")
                try:
                    # 消息元数据和活动计数放在同一个事务中写入。
                    async with UnitOfWork(self.bot.db_handler) as uow:
                        await uow.structured_speech_message.create(
                            message_id=sent.id,
                            webhook_id=webhook.id,
                            guild_id=qo.guild_id,
                            thread_id=qo.thread_id,
                            user_id=qo.user_id,
                            created_at=sent.created_at,
                        )
                        await uow.user_activity.update_user_activity(
                            UpdateUserActivityQo(
                                user_id=qo.user_id,
                                thread_id=qo.thread_id,
                                change=1,
                            )
                        )
                except Exception:
                    # 数据库事务失败时尽力删除已发送消息，避免留下未跟踪发言。
                    try:
                        await self.bot.api_scheduler.submit(sent.delete(), priority=1)
                    except Exception:
                        logger.exception("删除未成功记账的结构化消息 %s 失败。", sent.id)
                    raise
                return sent

    async def handle_message_deletions(
        self,
        qo: DeleteStructuredSpeechMessagesQo,
    ) -> list[StructuredSpeechDeletionResultDto]:
        """幂等回滚已删除结构化消息的活动计数并返回面板更新。"""
        async with self._deletion_lock:
            async with UnitOfWork(self.bot.db_handler) as uow:
                # 批量认领尚未处理的消息，避免重复删除事件造成重复扣减。
                records = await uow.structured_speech_message.claim_deletions(
                    message_ids=qo.message_ids,
                    deleted_at=datetime.now(timezone.utc),
                )
                changes = Counter((record.thread_id, record.user_id) for record in records)
                updates: list[StructuredSpeechDeletionResultDto] = []
                for (thread_id, user_id), count in changes.items():
                    # 相同用户和帖子中的删除量先聚合，再一次更新活动记录以避免 N+1。
                    activity = await uow.user_activity.update_user_activity(
                        UpdateUserActivityQo(
                            user_id=user_id,
                            thread_id=thread_id,
                            change=-count,
                        )
                    )
                    if EligibilityService.is_eligible(UserActivityDto.model_validate(activity)):
                        continue
                    details = await VotingLogic.remove_active_user_votes_in_thread(
                        uow=uow,
                        user_id=user_id,
                        thread_id=thread_id,
                    )
                    if details:
                        updates.append(
                            StructuredSpeechDeletionResultDto(
                                thread_id=thread_id,
                                vote_details=details,
                            )
                        )
                return updates

    async def _edit_slowmode(self, thread: discord.Thread, seconds: int) -> None:
        """通过统一调度器修改帖子慢速模式。"""
        await self.bot.api_scheduler.submit(
            thread.edit(
                slowmode_delay=seconds,
                reason="切换提案讨论模板发言模式",
            ),
            priority=1,
        )

    async def _set_mode_status(self, thread_id: int, status: str) -> None:
        """在独立事务中持久化模式状态。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            mode = await uow.structured_speech_mode.get(thread_id)
            if mode is None:
                raise RuntimeError(f"找不到帖子 {thread_id} 的模板发言模式记录。")
            mode.status = status
            mode.updated_at = datetime.now(timezone.utc)
            await uow.structured_speech_mode.save(mode)

    @staticmethod
    def _snapshot(mode: StructuredSpeechMode) -> StructuredSpeechModeDto:
        """把 ORM 模型转换为可跨会话使用的 DTO。"""
        return StructuredSpeechModeDto.model_validate(mode)
