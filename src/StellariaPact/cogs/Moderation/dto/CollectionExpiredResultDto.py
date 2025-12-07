from typing import Optional

from StellariaPact.cogs.Moderation.qo import BuildCollectionExpiredEmbedQo
from StellariaPact.share.BaseDto import BaseDto


class CollectionExpiredResultDto(BaseDto):
    """
    用于封装 handle_objection_collection_expired 逻辑层方法成功执行后的结果。
    """

    embed_qo: BuildCollectionExpiredEmbedQo
    notification_channel_id: Optional[int]
    original_vote_message_id: Optional[int]
