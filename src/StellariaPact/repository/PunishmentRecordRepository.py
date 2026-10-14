from datetime import datetime, timezone

from sqlalchemy import func
from sqlmodel import or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.models.PunishmentRecord import PunishmentRecord


class PunishmentRecordRepository:
    """处罚历史的写入与查询服务。"""

    def __init__(self, session: AsyncSession):
        """绑定数据库会话，后续操作在同一事务内完成。"""
        self.session = session

    async def create_record(
        self,
        *,
        guild_id: int,
        thread_id: int,
        target_user_id: int,
        moderator_id: int,
        reason: str,
        source_message_url: str | None,
        voting_allowed: bool,
        mute_end_time: datetime | None,
        counts_toward_cumulative: bool = False,
    ) -> PunishmentRecord:
        """写入一条处罚记录并立即刷新，返回持久化后的记录对象。"""
        # 构造处罚记录实体
        record = PunishmentRecord(
            guild_id=guild_id,
            thread_id=thread_id,
            target_user_id=target_user_id,
            moderator_id=moderator_id,
            reason=reason,
            source_message_url=source_message_url,
            voting_allowed=voting_allowed,
            mute_end_time=mute_end_time,
            counts_toward_cumulative=counts_toward_cumulative,
        )
        # 加入会话并刷新以获取数据库生成的默认值
        self.session.add(record)
        await self.session.flush()
        return record

    async def get_cumulative_count(self, *, thread_id: int, target_user_id: int) -> int:
        """统计尚未解除且计入累计处罚的记录。"""
        result = await self.session.exec(
            select(func.count(PunishmentRecord.id)).where(  # type: ignore
                PunishmentRecord.thread_id == thread_id,
                PunishmentRecord.target_user_id == target_user_id,
                PunishmentRecord.counts_toward_cumulative == True,  # noqa: E712
                PunishmentRecord.lifted_at == None,  # noqa: E711
            )
        )
        return result.one()

    async def get_latest(self, *, thread_id: int, target_user_id: int) -> PunishmentRecord | None:
        """取得最后一次处罚状态变更，包括已解除记录。"""
        result = await self.session.exec(
            select(PunishmentRecord)
            .where(
                PunishmentRecord.thread_id == thread_id,
                PunishmentRecord.target_user_id == target_user_id,
            )
            .order_by(PunishmentRecord.id.desc())  # type: ignore
            .limit(1)
        )
        return result.first()

    async def find_by_panel(
        self, *, guild_id: int, channel_id: int, message_id: int
    ) -> PunishmentRecord | None:
        """仅使用已登记的公示位置定位处罚，避免从消息正文猜测目标。"""
        result = await self.session.exec(
            select(PunishmentRecord).where(
                PunishmentRecord.guild_id == guild_id,
                or_(
                    (PunishmentRecord.thread_id == channel_id)
                    & (PunishmentRecord.source_publicity_message_id == message_id),
                    (PunishmentRecord.publicity_guild_id == guild_id)
                    & (PunishmentRecord.publicity_channel_id == channel_id)
                    & (PunishmentRecord.publicity_message_id == message_id),
                ),
            )
        )
        return result.first()

    async def mark_lifted(
        self, record: PunishmentRecord, *, moderator_id: int, reason: str
    ) -> None:
        """保留原处罚快照并登记解除信息，累计查询自动排除该记录。"""
        record.lifted_at = datetime.now(timezone.utc)
        record.lifted_by_id = moderator_id
        record.lift_reason = reason
        self.session.add(record)
        await self.session.flush()

    async def set_source_publicity_message(self, record_id: int, message_id: int) -> None:
        """保存原帖公示位置，包括正式公示区不可用时的降级面板。"""
        record = await self.session.get(PunishmentRecord, record_id)
        if record is None:
            raise ValueError(f"找不到帖子内处罚记录：{record_id}")
        record.source_publicity_message_id = message_id
        self.session.add(record)
        await self.session.flush()

    async def get_summary(
        self,
        *,
        thread_id: int,
        target_user_id: int,
        limit: int = 3,
    ) -> tuple[int, list[PunishmentRecord]]:
        """查询指定帖子中某用户的处罚总数与最近若干条记录。"""
        # 按帖子与用户过滤，一次查询同时获取总数和详情
        filters = (
            PunishmentRecord.thread_id == thread_id,
            PunishmentRecord.target_user_id == target_user_id,
        )
        # 子查询：统计符合条件的处罚总次数
        count_result = await self.session.exec(
            select(func.count(PunishmentRecord.id)).where(*filters)  # type: ignore
        )
        total = count_result.one()

        # 详情查询：按创建时间与主键倒序，取最近若干条
        records_result = await self.session.exec(
            select(PunishmentRecord)
            .where(*filters)
            .order_by(PunishmentRecord.created_at.desc(), PunishmentRecord.id.desc())  # type: ignore
            .limit(limit)
        )
        return total, list(records_result.all())

    async def set_publicity_message(
        self,
        record_id: int,
        *,
        guild_id: int,
        channel_id: int,
        message_id: int,
    ) -> PunishmentRecord:
        """保存帖子内处罚正式公示消息的完整位置。"""
        record = await self.session.get(PunishmentRecord, record_id)
        if record is None:
            raise ValueError(f"找不到帖子内处罚记录：{record_id}")
        record.publicity_guild_id = guild_id
        record.publicity_channel_id = channel_id
        record.publicity_message_id = message_id
        self.session.add(record)
        await self.session.flush()
        return record
