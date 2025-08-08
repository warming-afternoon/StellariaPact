from sqlmodel import SQLModel


class GetVoteDetailsQo(SQLModel):
    """
    获取投票详细信息的查询对象
    """

    message_id: int
