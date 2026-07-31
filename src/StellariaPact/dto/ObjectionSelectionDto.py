from datetime import datetime

from pydantic import BaseModel, Field


class ObjectionSelectionDto(BaseModel):
    """异议移除 Modal 中使用的稳定选项快照。"""

    id: int = Field(description="异议选项 ID")
    choice_index: int = Field(description="异议序号")
    choice_text: str = Field(description="异议内容")
    created_at: datetime = Field(description="异议创建时间")
