from datetime import datetime
from typing import Optional

from StellariaPact.share import BaseDto


class CreateVoteSessionQo(BaseDto):
    """
    创建投票会话的查询对象
    """

    guild_id: int
    """服务器ID"""
    thread_id: int
    """关联的帖子ID"""

    objection_id: Optional[int] = None
    """关联的异议ID (如果是异议投票)"""

    context_message_id: int
    """上下文消息ID (通常是帖子内的投票面板消息)"""

    realtime: bool = False
    """是否实时显示票数"""

    anonymous: bool = True
    """是否匿名投票"""

    notify_flag: bool = True
    """结束时是否通知相关方"""

    end_time: Optional[datetime] = None
    """投票结束时间"""

    total_choices: int = 0
    """投票选项总数"""
