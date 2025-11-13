from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from .OptionResult import OptionResult
from .VoterInfo import VoterInfo


class VoteDetailDto(BaseModel):
    """
    投票详细状态的数据传输对象
    """

    context_thread_id: int = Field(..., description="上下文帖子 ID")
    objection_id: Optional[int] = Field(None, description="关联的异议 ID")
    voting_channel_message_id: Optional[int] = Field(None, description="投票频道中的消息 ID")
    is_anonymous: bool = Field(..., description="是否匿名")
    realtime_flag: bool = Field(..., description="是否实时显示票数")
    notify_flag: bool = Field(..., description="结束时是否通知")
    end_time: Optional[datetime] = Field(None, description="投票结束时间")
    context_message_id: Optional[int] = Field(None, description="上下文消息 ID")
    status: int = Field(..., description="投票状态: 1-进行中, 0-已结束")
    total_choices: int = Field(..., description="选项总数")
    total_approve_votes: int = Field(default=0, description="总赞成票数")
    total_reject_votes: int = Field(default=0, description="总反对票数")
    total_votes: int = Field(default=0, description="总票数")
    options: List[OptionResult] = Field(default_factory=list, description="所有选项及其结果")
    voters: List[VoterInfo] = Field(default_factory=list, description="所有投票者信息 (非匿名时)")
