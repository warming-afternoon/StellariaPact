from dataclasses import dataclass
from typing import Optional

from ....cogs.Moderation.qo.BuildVoteResultEmbedQo import \
    BuildVoteResultEmbedQo
from ....share.BaseDto import BaseDto


@dataclass
class VoteFinishedResultDto(BaseDto):
    """
    用于封装 handle_objection_vote_finished 逻辑层方法成功执行后的结果。
    """

    embed_qo: BuildVoteResultEmbedQo
    channel_id: Optional[int]
    message_id: Optional[int]