from typing import List, Optional

from ....cogs.Moderation.qo.BuildVoteResultEmbedQo import \
    BuildVoteResultEmbedQo
from ....share.BaseDto import BaseDto


class VoteFinishedResultDto(BaseDto):
    """
    用于封装 handle_objection_vote_finished 逻辑层方法成功执行后的结果。
    """

    embed_qo: BuildVoteResultEmbedQo
    is_passed: bool
    original_proposal_thread_id: int
    objection_thread_id: Optional[int]
    notification_channel_id: Optional[int]
    original_vote_message_id: Optional[int]
    approve_voter_ids: Optional[List[int]] = None
    reject_voter_ids: Optional[List[int]] = None
