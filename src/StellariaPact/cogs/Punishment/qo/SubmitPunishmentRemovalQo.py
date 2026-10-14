from dataclasses import dataclass

import discord


@dataclass(slots=True)
class SubmitPunishmentRemovalQo:
    """传递解除表单绑定的原帖、用户和管理员输入。"""

    thread: discord.Thread
    """被解除处罚所属的原提案帖。"""

    target_user: discord.User | discord.Member
    """被解除处罚的真实用户。"""

    expected_record_id: int
    """打开表单时绑定的最新处罚记录 ID。"""

    reason: str
    """管理员填写的解除理由。"""
