from dataclasses import dataclass

import discord


@dataclass
class EditObjectionReasonQo:
    """
    用于从 EditObjectionReasonModal 分派事件的数据查询对象。
    """

    interaction: discord.Interaction
    objection_id: int
    new_reason: str