from pydantic import BaseModel, Field


class DeleteVoteQo(BaseModel):
    """
    删除用户投票
    """

    user_id: int = Field(..., description="投票用户的Discord ID")
    message_id: int = Field(..., description="投票面板消息的ID")
    choice_index: int = Field(default=1, description="投票选项索引 (从1开始)")
