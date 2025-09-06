from sqlmodel import SQLModel


class AdjustVoteTimeQo(SQLModel):
    """
    调整投票结束时间的查询对象
    """
    
    message_id: int
    hours_to_adjust: int
