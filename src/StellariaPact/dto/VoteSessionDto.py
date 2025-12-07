from datetime import datetime
from typing import Optional

from sqlmodel import Field

from StellariaPact.share import BaseDto


class VoteSessionDto(BaseDto):
    """
    投票会话的数据传输对象，用于在服务层和视图层之间传递数据。
    """

    id: int = Field(..., description="投票会话的唯一标识符")
    guild_id: int = Field(..., description="服务器ID")
    total_choices: int = Field(..., description="选项总数")
    context_thread_id: int = Field(..., description="投票发生的帖子ID")
    objection_id: Optional[int] = Field(None, alias="objection_id", description="关联的异议ID")
    context_message_id: Optional[int] = Field(None, description="投票面板消息的ID")
    voting_channel_message_id: Optional[int] = Field(
        None, description="投票频道中镜像投票消息的ID"
    )
    anonymous_flag: bool = Field(..., alias="anonymous_flag", description="是否为匿名投票")
    realtime_flag: bool = Field(..., alias="realtime_flag", description="是否实时展示投票进度")
    notify_flag: bool = Field(..., alias="notify_flag", description="投票结束时是否通知相关方")
    status: int = Field(..., description="投票状态: 0-已结束, 1-进行中")
    end_time: Optional[datetime] = Field(None, alias="end_time", description="投票截止时间")
