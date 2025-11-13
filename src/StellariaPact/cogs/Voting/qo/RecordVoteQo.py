from sqlmodel import Field, SQLModel


class RecordVoteQo(SQLModel):
    """
    记录用户投票的查询对象
    """

    user_id: int = Field(..., description="投票用户的Discord ID")
    message_id: int = Field(..., description="投票面板消息的ID")
    thread_id: int = Field(..., description="投票发生的帖子ID")
    choice: int = Field(..., description="用户的投票选择: 0-反对, 1-赞成")
    choice_index: int = Field(default=1, description="投票选项索引 (从1开始)")
