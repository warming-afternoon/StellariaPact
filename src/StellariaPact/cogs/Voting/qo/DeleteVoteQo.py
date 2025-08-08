from pydantic import BaseModel


class DeleteVoteQo(BaseModel):
    """
    QO for deleting a user's vote.
    """

    user_id: int
    message_id: int