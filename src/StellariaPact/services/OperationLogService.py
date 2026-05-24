import logging

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from StellariaPact.models.OperationLog import OperationLog

logger = logging.getLogger(__name__)


class OperationLogService:
    """操作记录服务"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def log_operation(
        self,
        operator_id: int,
        operator_name: str,
        operator_display_name: str,
        op_type: int,
        action: str,
        target_type: str,
        target_id: int,
        guild_id: int,
        detail: str | None = None,
    ) -> OperationLog:
        """创建一条操作记录。"""
        log = OperationLog(
            operator_id=operator_id,
            operator_name=operator_name,
            operator_display_name=operator_display_name,
            op_type=op_type,
            action=action,
            target_type=target_type,
            target_id=target_id,
            guild_id=guild_id,
            detail=detail,
        )
        self.session.add(log)
        return log

    async def query_by_target(self, target_type: str, target_id: int) -> list[OperationLog]:
        """按目标查询操作历史。"""
        statement = (
            select(OperationLog)
            .where(OperationLog.target_type == target_type, OperationLog.target_id == target_id)
            .order_by(OperationLog.created_at.desc())
        )
        result = await self.session.exec(statement)
        return list(result.all())
