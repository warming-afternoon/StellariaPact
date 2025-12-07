from StellariaPact.share import BaseDto


class BuildObjectionReviewResultEmbedQo(BaseDto):
    """
    用于构建异议审核结果 Embed 的查询对象。
    """

    guild_id: int
    proposal_title: str
    proposal_thread_id: int
    objector_id: int
    objection_reason: str
    moderator_id: int
    review_reason: str
    is_approve: bool
