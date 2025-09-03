from pydantic import BaseModel


class DeleteVoteQo(BaseModel):
    """
    删除用户投票
    """

    user_id: int
    message_id: int
