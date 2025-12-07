from StellariaPact.cogs.Voting.dto import VoteDetailDto
from StellariaPact.share import BaseDto


class UpdatePublicVoteCountsQo(BaseDto):
    """
    用于更新公共投票面板计数的QO。
    """

    thread_id: int
    original_message_id: int
    vote_details: VoteDetailDto
