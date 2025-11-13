from pydantic import BaseModel, Field


class OptionResult(BaseModel):
    """
    单个投票选项的结果
    """

    choice_index: int = Field(..., description="选项的索引")
    choice_text: str = Field(..., description="选项的显示文本")
    approve_votes: int = Field(..., description="赞成票数")
    reject_votes: int = Field(..., description="反对票数")
    total_votes: int = Field(..., description="总票数")
