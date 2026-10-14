from dataclasses import dataclass

import discord


@dataclass(slots=True)
class SubmitThreadPunishmentQo:
    """传递人工处罚表单输入，由控制器校验并组织处罚流程。"""

    target_user: discord.User | discord.Member
    """打开表单时解析出的真实被处罚用户。"""

    target_message: discord.Message | None
    """右键选中的原始发言，作为处罚依据转发。"""

    voting_input: str
    """是否保留投票权的原始表单输入。"""

    mute_minutes_input: str
    """自当前起算禁言分钟数的原始表单输入。"""

    reason: str
    """管理员填写的处罚理由。"""

    evidence: tuple[discord.Attachment, ...] = ()
    """可选处罚材料附件，控制器负责读取并释放文件。"""
