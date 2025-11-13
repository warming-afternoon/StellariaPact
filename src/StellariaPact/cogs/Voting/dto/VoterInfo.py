from pydantic import BaseModel, Field


class VoterInfo(BaseModel):
    """
    单个投票者的信息
    """

    user_id: int = Field(..., description="投票者的 Discord 用户 ID")
    choice: int = Field(..., description="用户的选项: 1-赞成, 0-反对")
    choice_index: int = Field(..., description="投票针对的选项索引")
