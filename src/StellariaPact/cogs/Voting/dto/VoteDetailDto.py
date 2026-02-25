from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from .OptionResult import OptionResult
from .VoterInfo import VoterInfo


class VoteDetailDto(BaseModel):
    """
    投票详细状态的数据传输对象
    """

    guild_id: int = Field(..., description="服务器 ID")
    """投票所属服务器 ID。"""

    context_thread_id: int = Field(..., description="上下文帖子 ID")
    """投票所在帖子 ID。"""

    objection_id: Optional[int] = Field(None, description="关联的异议 ID")
    """关联的异议 ID；无异议场景为 `None`。"""

    voting_channel_message_id: Optional[int] = Field(None, description="投票频道中的消息 ID")
    """投票频道中的展示消息 ID；未同步时为 `None`。"""

    is_anonymous: bool = Field(..., description="是否匿名")
    """是否为匿名投票。"""

    realtime_flag: bool = Field(..., description="是否实时显示票数")
    """是否实时展示票数统计。"""

    notify_flag: bool = Field(..., description="结束时是否通知")
    """投票结束后是否发送通知。"""

    end_time: Optional[datetime] = Field(None, description="投票结束时间")
    """投票结束时间；无截止时间时为 `None`。"""

    context_message_id: Optional[int] = Field(None, description="上下文消息 ID")
    """帖子中对应投票主消息 ID。"""

    status: int = Field(..., description="投票状态: 1-进行中, 0-已结束")
    """投票状态（`1` 进行中，`0` 已结束）。"""

    total_choices: int = Field(..., description="选项总数")
    """当前投票总选项数。"""

    total_approve_votes: int = Field(default=0, description="总赞成票数")
    """所有选项累计赞成票数。"""

    total_reject_votes: int = Field(default=0, description="总反对票数")
    """所有选项累计反对票数。"""

    total_votes: int = Field(default=0, description="总票数")
    """所有选项累计总投票数。"""

    options: List[OptionResult] = Field(default_factory=list, description="所有选项及其结果 (兼容旧处理)")
    """兼容旧逻辑的扁平化选项结果集合。"""

    normal_options: List[OptionResult] = Field(default_factory=list, description="普通投票选项")
    """普通投票选项结果集合。"""

    objection_options: List[OptionResult] = Field(default_factory=list, description="异议投票选项")
    """异议投票选项结果集合。"""

    voters: List[VoterInfo] = Field(default_factory=list, description="所有投票者信息 (非匿名时)")
    """投票者明细（仅非匿名投票时有效）。"""
