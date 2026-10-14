from dataclasses import dataclass


@dataclass(slots=True)
class LiftThreadPunishmentQo:
    """传递解除处罚时需要重新验证的目标和记录。"""

    thread_id: int
    """被解除处罚所属的提案帖子 ID。"""

    target_user_id: int
    """被解除处罚的用户 ID。"""

    expected_record_id: int
    """打开表单时绑定的最新处罚记录 ID。"""

    moderator_id: int
    """执行解除操作的管理员 ID。"""

    reason: str
    """管理员填写的解除理由。"""
