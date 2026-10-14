import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from StellariaPact.cogs.Voting.VotingLogic import VotingLogic
from StellariaPact.share import StellariaPactBot, UnitOfWork
from StellariaPact.share.BusinessRuleError import BusinessRuleError
from StellariaPact.share.enums import LogOperationType, PunishmentType

from ..constants import OFF_TOPIC_REASON, PERMANENT_THREAD_MUTE, chinese_number
from ..dto import PunishmentRecordDto, ThreadPunishmentHistoryDto, ThreadPunishmentResult
from ..qo import (
    ApplyThreadPunishmentQo,
    LiftThreadPunishmentQo,
    QueryThreadPunishmentQo,
    ResolvePunishmentPanelQo,
    SavePunishmentPanelQo,
)

logger = logging.getLogger(__name__)


class PunishmentLogic:
    def __init__(self, bot: StellariaPactBot):
        """保存数据库依赖及跨业务层实例共享的帖子处罚锁。"""
        self.bot = bot
        self._user_locks = bot.__dict__.setdefault("_thread_punishment_locks", {})

    async def get_thread_history(self, qo: QueryThreadPunishmentQo) -> ThreadPunishmentHistoryDto:
        """查询处罚摘要，并在事务内将 ORM 记录转换为界面快照。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 以记录 ID 确定最新状态，解除预检不依赖显示记录的时间排序。
            latest = await uow.punishment_record.get_latest(
                thread_id=qo.thread_id, target_user_id=qo.target_user_id
            )
            if qo.for_removal:
                if latest is None:
                    raise BusinessRuleError("该用户在当前帖子中没有处罚记录。")
                if qo.selected_record_id is not None and qo.selected_record_id != latest.id:
                    raise BusinessRuleError("该处罚已被后续处罚覆盖，请对最新处罚重新操作。")
                if latest.lifted_at is not None:
                    raise BusinessRuleError("该处罚已经解除，无需重复操作。")

            # 仓储按帖子和用户一次性取得最近记录，不逐条追加数据库查询。
            total, records = await uow.punishment_record.get_summary(
                thread_id=qo.thread_id, target_user_id=qo.target_user_id
            )
            count = await uow.punishment_record.get_cumulative_count(
                thread_id=qo.thread_id, target_user_id=qo.target_user_id
            )
            return ThreadPunishmentHistoryDto(
                total=total,
                cumulative_count=count,
                latest=PunishmentRecordDto.model_validate(latest) if latest is not None else None,
                records=[PunishmentRecordDto.model_validate(record) for record in records],
            )

    async def resolve_punishment_panel(
        self, qo: ResolvePunishmentPanelQo
    ) -> PunishmentRecordDto | None:
        """从已登记的面板位置或可信旧面板链接解析处罚快照。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 优先匹配数据库登记的原帖或正式公示位置。
            record = await uow.punishment_record.find_by_panel(
                guild_id=qo.guild_id, channel_id=qo.channel_id, message_id=qo.message_id
            )
            if (
                record is None
                and qo.legacy_channel_id is not None
                and qo.legacy_message_id is not None
            ):
                # 旧链接只能关联同一原帖的记录，不能借用其他帖子的公示。
                record = await uow.punishment_record.find_by_panel(
                    guild_id=qo.guild_id,
                    channel_id=qo.legacy_channel_id,
                    message_id=qo.legacy_message_id,
                )
                if record is not None and record.thread_id != qo.channel_id:
                    record = None
            return PunishmentRecordDto.model_validate(record) if record is not None else None

    async def apply_thread_punishment(self, qo: ApplyThreadPunishmentQo) -> ThreadPunishmentResult:
        """原子地计算累计档位、更新处罚状态和历史，并同步缓存。"""
        # 在共享锁内完成档位计算、数据库写入和缓存同步。
        reason, voting_allowed, mute_end_time = qo.reason, qo.voting_allowed, qo.mute_end_time
        quick_mode = qo.quick_mode
        if quick_mode not in (None, "cumulative", "off_topic"):
            raise ValueError("不支持的快速处罚类型。")
        lock = self._user_locks.setdefault((qo.thread_id, qo.target_user_id), asyncio.Lock())
        async with lock:
            async with UnitOfWork(self.bot.db_handler) as uow:
                count = await uow.punishment_record.get_cumulative_count(
                    thread_id=qo.thread_id, target_user_id=qo.target_user_id
                )
                # 累计次数与处罚历史在同一事务中读取和写入。
                counts_toward_cumulative = not voting_allowed or mute_end_time is not None
                if quick_mode is not None:
                    counts_toward_cumulative = quick_mode == "cumulative"
                    now = datetime.now(timezone.utc)
                    if quick_mode == "cumulative":
                        ordinal = count + 1
                        minutes = {1: 5, 2: 10, 3: 30}.get(ordinal)
                        mute_end_time = (
                            now + timedelta(minutes=minutes)
                            if minutes is not None
                            else PERMANENT_THREAD_MUTE
                        )
                        reason = f"{OFF_TOPIC_REASON}，{chinese_number(ordinal)}次处罚"
                    else:
                        if count and not qo.off_topic_confirmed:
                            raise BusinessRuleError(
                                f"该用户已有 {count} 次累计处罚，请重新使用指令确认处罚方式。"
                            )
                        mute_end_time = now + timedelta(minutes=5)
                        reason = OFF_TOPIC_REASON
                    # 快速处罚不会缩短已有禁言或恢复已被剥夺的投票权。
                    voting_allowed = True
                    existing = await uow.user_activity.get_user_activity(
                        qo.target_user_id, qo.thread_id
                    )
                    if existing is not None:
                        voting_allowed = existing.validation != 0
                        if existing.mute_end_time is not None:
                            mute_end_time = max(existing.mute_end_time, mute_end_time)

                # 更新资格状态并记录实际生效的处罚结果。
                await uow.user_activity.update_user_validation_status(
                    user_id=qo.target_user_id,
                    thread_id=qo.thread_id,
                    is_valid=voting_allowed,
                    mute_end_time=mute_end_time,
                )
                record = await uow.punishment_record.create_record(
                    guild_id=qo.guild_id,
                    thread_id=qo.thread_id,
                    target_user_id=qo.target_user_id,
                    moderator_id=qo.moderator_id,
                    reason=reason,
                    source_message_url=qo.source_message_url,
                    voting_allowed=voting_allowed,
                    mute_end_time=mute_end_time,
                    counts_toward_cumulative=counts_toward_cumulative,
                )
                if record.id is None:
                    raise RuntimeError("帖子内处罚记录缺少数据库主键。")
                result = ThreadPunishmentResult(
                    punishment_record_id=record.id,
                    vote_details_to_update=[],
                    reason=reason,
                    cumulative_count=count + int(counts_toward_cumulative),
                    voting_allowed=voting_allowed,
                    mute_end_time=mute_end_time,
                )
                # 剥夺投票权时同步清理仍在进行中的投票。
                if not voting_allowed:
                    result.vote_details_to_update = (
                        await VotingLogic.remove_active_user_votes_in_thread(
                            uow=uow, user_id=qo.target_user_id, thread_id=qo.thread_id
                        )
                    )
                await uow.commit()
            # 在共享锁内派发，避免旧操作的事件覆盖新操作的缓存。
            self.bot.dispatch(
                "thread_mute_updated", qo.thread_id, qo.target_user_id, mute_end_time
            )
            for details in result.vote_details_to_update:
                self.bot.dispatch("vote_details_updated", details)
            return result

    async def lift_thread_punishment(self, qo: LiftThreadPunishmentQo) -> int:
        """仅解除打开表单时的最新处罚，返回解除后的累计次数。"""
        if not qo.reason.strip():
            raise BusinessRuleError("请输入解除理由。")
        lock = self._user_locks.setdefault((qo.thread_id, qo.target_user_id), asyncio.Lock())
        async with lock:
            async with UnitOfWork(self.bot.db_handler) as uow:
                # 提交时重新验证最新记录，阻止过期表单及重复解除。
                latest = await uow.punishment_record.get_latest(
                    thread_id=qo.thread_id, target_user_id=qo.target_user_id
                )
                if latest is None or latest.id != qo.expected_record_id:
                    raise BusinessRuleError("该处罚已被后续处罚覆盖，请对最新处罚重新操作。")
                if latest.lifted_at is not None:
                    raise BusinessRuleError("该处罚已经解除，无需重复操作。")
                activity = await uow.user_activity.get_user_activity(
                    qo.target_user_id, qo.thread_id
                )
                now = datetime.now(timezone.utc)
                if activity is None or (
                    activity.validation != 0
                    and (activity.mute_end_time is None or activity.mute_end_time <= now)
                ):
                    raise BusinessRuleError("该用户在当前帖子中没有生效中的处罚。")
                # 同时解除当前状态并登记解除记录，原处罚快照保持可查询。
                await uow.user_activity.clear_punishment(qo.target_user_id, qo.thread_id)
                await uow.punishment_record.mark_lifted(
                    latest, moderator_id=qo.moderator_id, reason=qo.reason.strip()
                )
                count = await uow.punishment_record.get_cumulative_count(
                    thread_id=qo.thread_id, target_user_id=qo.target_user_id
                )
                await uow.commit()
            # 提交成功后在共享锁内同步缓存，避免事件次序倒置。
            self.bot.dispatch("thread_mute_updated", qo.thread_id, qo.target_user_id, None)
            return count

    async def save_publicity_panel(self, qo: SavePunishmentPanelQo) -> None:
        """在独立事务中登记已发送面板的位置，不回滚原处罚。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            # 正式公示保留完整位置，原帖公示只保存消息 ID。
            if qo.is_source:
                await uow.punishment_record.set_source_publicity_message(
                    qo.record_id, qo.message_id
                )
            else:
                await uow.punishment_record.set_publicity_message(
                    qo.record_id,
                    guild_id=qo.guild_id,
                    channel_id=qo.channel_id,
                    message_id=qo.message_id,
                )
            await uow.commit()

    async def apply_permanent_restriction(
        self,
        *,
        punishment_type: PunishmentType,
        target_user_id: int,
        moderator_id: int,
        origin_guild_id: int,
        origin_channel_id: int,
        reason: str,
        evidence_url: str | None,
        evidence_filename: str | None,
        moderator_name: str,
        moderator_display_name: str,
    ) -> int:
        """按分类永久剥夺用户的提案权限。"""
        action = {
            PunishmentType.PERMANENT_VOTING: "apply_permanent_voting",
            PunishmentType.PERMANENT_OBJECTION_CREATION: "apply_permanent_objection_creation",
        }.get(punishment_type)
        if action is None:
            raise ValueError("不支持的永久权限处罚分类。")
        async with UnitOfWork(self.bot.db_handler) as uow:
            punishment = await uow.global_proposal_punishment.create_punishment(
                target_user_id=target_user_id,
                moderator_id=moderator_id,
                origin_guild_id=origin_guild_id,
                origin_channel_id=origin_channel_id,
                punishment_type=punishment_type,
                reason=reason,
                evidence_url=evidence_url,
                evidence_filename=evidence_filename,
            )
            punishment_id = self._require_punishment_id(punishment.id)
            await self._log_global_punishment_operation(
                uow=uow,
                punishment_id=punishment_id,
                target_user_id=target_user_id,
                moderator_id=moderator_id,
                moderator_name=moderator_name,
                moderator_display_name=moderator_display_name,
                guild_id=origin_guild_id,
                action=action,
                punishment_type=punishment_type,
                reason=reason,
                origin_channel_id=origin_channel_id,
            )
            await uow.commit()
            return punishment_id

    async def lift_permanent_restriction(
        self,
        *,
        punishment_type: PunishmentType,
        target_user_id: int,
        lifted_by_id: int,
        lift_reason: str,
        moderator_name: str,
        moderator_display_name: str,
        guild_id: int,
        channel_id: int,
    ) -> tuple[int, datetime]:
        """按分类解除用户的永久提案权限限制。"""
        action = {
            PunishmentType.PERMANENT_VOTING: "lift_permanent_voting",
            PunishmentType.PERMANENT_OBJECTION_CREATION: "lift_permanent_objection_creation",
        }.get(punishment_type)
        if action is None:
            raise ValueError("不支持的永久权限处罚分类。")
        async with UnitOfWork(self.bot.db_handler) as uow:
            restriction = await uow.global_proposal_punishment.lift_punishment(
                target_user_id=target_user_id,
                punishment_type=punishment_type,
                lifted_by_id=lifted_by_id,
                lift_reason=lift_reason,
            )
            punishment_id = self._require_punishment_id(restriction.id)
            original_created_at = restriction.created_at
            await self._log_global_punishment_operation(
                uow=uow,
                punishment_id=punishment_id,
                target_user_id=target_user_id,
                moderator_id=lifted_by_id,
                moderator_name=moderator_name,
                moderator_display_name=moderator_display_name,
                guild_id=guild_id,
                action=action,
                punishment_type=punishment_type,
                reason=lift_reason,
                origin_channel_id=channel_id,
            )
            await uow.commit()
            return punishment_id, original_created_at

    async def apply_global_voting_restriction(self, **kwargs) -> int:
        """兼容旧调用：永久剥夺投票资格。"""
        return await self.apply_permanent_restriction(
            punishment_type=PunishmentType.PERMANENT_VOTING,
            **kwargs,
        )

    async def lift_global_voting_restriction(self, **kwargs) -> tuple[int, datetime]:
        """兼容旧调用：解除永久投票资格限制。"""
        return await self.lift_permanent_restriction(
            punishment_type=PunishmentType.PERMANENT_VOTING,
            **kwargs,
        )

    async def apply_proposal_violation_punishment(
        self,
        *,
        target_user_id: int,
        moderator_id: int,
        origin_guild_id: int,
        origin_channel_id: int,
        days: int,
        reason: str,
        evidence_url: str | None,
        evidence_filename: str | None,
        moderator_name: str,
        moderator_display_name: str,
    ) -> tuple[int, datetime]:
        """创建用户的机器人全局提案违规处罚。"""
        if not 1 <= days <= 30:
            raise ValueError("提案违规处罚天数必须在 1 至 30 天之间。")
        expires_at = datetime.now(timezone.utc) + timedelta(days=days)
        async with UnitOfWork(self.bot.db_handler) as uow:
            punishment = await uow.global_proposal_punishment.create_punishment(
                target_user_id=target_user_id,
                moderator_id=moderator_id,
                origin_guild_id=origin_guild_id,
                origin_channel_id=origin_channel_id,
                punishment_type=PunishmentType.PROPOSAL_VIOLATION,
                reason=reason,
                expires_at=expires_at,
                evidence_url=evidence_url,
                evidence_filename=evidence_filename,
            )
            punishment_id = self._require_punishment_id(punishment.id)
            await self._log_global_punishment_operation(
                uow=uow,
                punishment_id=punishment_id,
                target_user_id=target_user_id,
                moderator_id=moderator_id,
                moderator_name=moderator_name,
                moderator_display_name=moderator_display_name,
                guild_id=origin_guild_id,
                action="apply_proposal_violation",
                punishment_type=PunishmentType.PROPOSAL_VIOLATION,
                reason=reason,
                origin_channel_id=origin_channel_id,
                expires_at=expires_at,
            )
            await uow.commit()
            return punishment_id, expires_at

    async def lift_proposal_violation_punishment(
        self,
        *,
        target_user_id: int,
        lifted_by_id: int,
        lift_reason: str,
        moderator_name: str,
        moderator_display_name: str,
        guild_id: int,
        channel_id: int,
    ) -> tuple[int, datetime, datetime]:
        """提前解除用户的机器人全局提案违规处罚。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            punishment = await uow.global_proposal_punishment.lift_punishment(
                target_user_id=target_user_id,
                punishment_type=PunishmentType.PROPOSAL_VIOLATION,
                lifted_by_id=lifted_by_id,
                lift_reason=lift_reason,
            )
            if punishment.expires_at is None:
                raise ValueError("提案违规处罚缺少截止时间。")
            punishment_id = self._require_punishment_id(punishment.id)
            result = (punishment_id, punishment.created_at, punishment.expires_at)
            await self._log_global_punishment_operation(
                uow=uow,
                punishment_id=punishment_id,
                target_user_id=target_user_id,
                moderator_id=lifted_by_id,
                moderator_name=moderator_name,
                moderator_display_name=moderator_display_name,
                guild_id=guild_id,
                action="lift_proposal_violation",
                punishment_type=PunishmentType.PROPOSAL_VIOLATION,
                reason=lift_reason,
                origin_channel_id=channel_id,
            )
            await uow.commit()
            return result

    async def set_punishment_message_id(
        self,
        punishment_id: int,
        message_id: int,
    ) -> None:
        """在独立事务中保存原始处罚公示消息 ID。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            await uow.global_proposal_punishment.set_punishment_message_id(
                punishment_id,
                message_id,
            )
            await uow.commit()

    async def set_resolution_message(
        self,
        punishment_id: int,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int,
    ) -> None:
        """在独立事务中保存解除公示消息的完整位置。"""
        async with UnitOfWork(self.bot.db_handler) as uow:
            await uow.global_proposal_punishment.set_resolution_message(
                punishment_id,
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=message_id,
            )
            await uow.commit()

    @staticmethod
    def _require_punishment_id(punishment_id: int | None) -> int:
        """确保已刷新处罚记录取得数据库主键。"""
        if punishment_id is None:
            raise RuntimeError("全局提案处罚记录缺少数据库主键。")
        return punishment_id

    @staticmethod
    async def _log_global_punishment_operation(
        *,
        uow: UnitOfWork,
        punishment_id: int,
        target_user_id: int,
        moderator_id: int,
        moderator_name: str,
        moderator_display_name: str,
        guild_id: int,
        action: str,
        punishment_type: PunishmentType,
        reason: str,
        origin_channel_id: int | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        """在处罚事务内写入不包含临时附件链接的结构化审计记录。"""
        detail = {
            "target_user_id": target_user_id,
            "punishment_type": punishment_type.value,
            "reason": reason,
        }
        if origin_channel_id is not None:
            detail["origin_channel_id"] = origin_channel_id
        if expires_at is not None:
            detail["expires_at"] = expires_at.isoformat()
        await uow.operation_log.log_operation(
            operator_id=moderator_id,
            operator_name=moderator_name,
            operator_display_name=moderator_display_name,
            op_type=LogOperationType.PUNISHMENT,
            action=action,
            target_type="global_proposal_punishment",
            target_id=punishment_id,
            guild_id=guild_id,
            detail=json.dumps(detail, ensure_ascii=False),
        )
