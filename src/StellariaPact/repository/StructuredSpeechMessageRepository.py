from datetime import datetime
from typing import Iterable

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.models.StructuredSpeechMessage import StructuredSpeechMessage


class StructuredSpeechMessageRepository:
    """封装结构化发言消息元数据表的数据库操作。"""

    def __init__(self, session: AsyncSession):
        """绑定当前工作单元的数据库会话。"""
        self.session = session

    async def get_webhook_ids(self) -> set[int]:
        """一次查询历史结构化消息使用过的全部 Webhook ID。"""
        result = await self.session.exec(select(StructuredSpeechMessage.webhook_id).distinct())
        return set(result.all())

    async def get_last(
        self,
        *,
        thread_id: int,
        user_id: int,
    ) -> StructuredSpeechMessage | None:
        """查询用户在帖子中的最近一次成功结构化发言。"""
        result = await self.session.exec(
            select(StructuredSpeechMessage)
            .where(
                StructuredSpeechMessage.thread_id == thread_id,
                StructuredSpeechMessage.user_id == user_id,
            )
            .order_by(col(StructuredSpeechMessage.created_at).desc())
            .limit(1)
        )
        return result.one_or_none()

    async def create(
        self,
        *,
        message_id: int,
        webhook_id: int,
        guild_id: int,
        thread_id: int,
        user_id: int,
        created_at: datetime,
    ) -> StructuredSpeechMessage:
        """记录已成功发送的结构化消息元数据。"""
        record = StructuredSpeechMessage(
            message_id=message_id,
            webhook_id=webhook_id,
            guild_id=guild_id,
            thread_id=thread_id,
            user_id=user_id,
            created_at=created_at,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def claim_deletions(
        self,
        *,
        message_ids: Iterable[int],
        deleted_at: datetime,
    ) -> list[StructuredSpeechMessage]:
        """批量认领尚未回滚的删除消息并标记删除时间。"""
        ids = tuple(set(message_ids))
        if not ids:
            return []
        result = await self.session.exec(
            select(StructuredSpeechMessage).where(
                col(StructuredSpeechMessage.message_id).in_(ids),
                col(StructuredSpeechMessage.deleted_at).is_(None),
            )
        )
        # 一次读取并更新整批记录，避免逐消息查询造成 N+1。
        records = list(result.all())
        for record in records:
            record.deleted_at = deleted_at
            self.session.add(record)
        await self.session.flush()
        return records
