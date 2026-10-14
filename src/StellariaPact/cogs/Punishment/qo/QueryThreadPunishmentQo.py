from dataclasses import dataclass


@dataclass(slots=True)
class QueryThreadPunishmentQo:
    """传递本帖处罚查询和解除表单预检所需条件。"""

    thread_id: int
    """查询处罚记录的提案帖子 ID。"""

    target_user_id: int
    """查询处罚记录的用户 ID。"""

    for_removal: bool = False
    """是否同时检查最新处罚能否打开解除表单。"""

    selected_record_id: int | None = None
    """右键处罚面板时选中的记录 ID，普通用户消息不传。"""
