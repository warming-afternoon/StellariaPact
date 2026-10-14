from dataclasses import dataclass

import discord


@dataclass(slots=True)
class SubmitQuickPunishmentQo:
    """传递消息菜单或确认表单选择的快速处罚方式。"""

    message: discord.Message
    """处罚来源消息，用于验证帖子并转发证据。"""

    target_user: discord.User | discord.Member
    """已经解析出的真实消息作者。"""

    cumulative: bool
    """是否使用累计升级处罚，否时使用歪楼滑坡处罚。"""

    off_topic_confirmed: bool = False
    """管理员是否已确认在有累计记录时继续歪楼滑坡处罚。"""
