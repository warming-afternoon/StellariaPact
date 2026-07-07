from datetime import datetime

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.models.PunishmentRecord import PunishmentRecord


class PunishmentRecordService:
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
        )
        # 加入会话并刷新以获取数据库生成的默认值
        self.session.add(record)
        await self.session.flush()
        return record

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
