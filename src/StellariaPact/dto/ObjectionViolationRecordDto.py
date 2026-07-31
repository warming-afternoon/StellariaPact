from datetime import datetime

from pydantic import BaseModel, Field


class ObjectionViolationRecordDto(BaseModel):
    """用户恶意违规异议查询结果中的单条记录。"""

    option_id: int = Field(description="异议选项 ID")
    choice_text: str = Field(description="异议内容")
    resolution_description: str | None = Field(default=None, description="违规描述")
    created_at: datetime = Field(description="异议提出时间")
    closed_at: datetime = Field(description="异议关闭时间")
    guild_id: int = Field(description="所属服务器 ID")
    thread_id: int = Field(description="所属提案帖子 ID")
    context_message_id: int | None = Field(default=None, description="投票面板消息 ID")
