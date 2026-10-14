from dataclasses import dataclass

from .PunishmentRecordDto import PunishmentRecordDto


@dataclass(slots=True)
class ThreadPunishmentHistoryDto:
    """表示本帖处罚摘要、最新记录及最近记录的独立快照。"""

    total: int
    """包括已解除记录在内的历史记录总数。"""

    cumulative_count: int
    """当前尚未解除且计入累计处罚的次数。"""

    latest: PunishmentRecordDto | None
    """最后一次处罚状态变更的记录快照。"""

    records: list[PunishmentRecordDto]
    """按时间倒序排列的最近三条处罚记录快照。"""
