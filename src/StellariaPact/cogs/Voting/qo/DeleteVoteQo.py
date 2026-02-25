from pydantic import BaseModel, Field


class DeleteVoteQo(BaseModel):
    """
    删除用户投票
    """

    user_id: int = Field(..., description="投票用户的Discord ID")
    message_id: int = Field(..., description="投票面板消息的ID")
    option_type: int = Field(default=0, description="投票选项类型: 0-普通投票, 1-异议投票")
    choice_index: int = Field(default=1, description="投票选项索引 (从1开始)")
