from sqlmodel import SQLModel


class RecordVoteQo(SQLModel):
    """
    记录用户投票的查询对象
    """

    user_id: int
    thread_id: int
    choice: int
