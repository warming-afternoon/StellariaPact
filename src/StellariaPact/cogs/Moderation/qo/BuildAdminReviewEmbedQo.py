from StellariaPact.share import BaseDto


class BuildAdminReviewEmbedQo(BaseDto):
    """
    用于构建管理员审核Embed的数据查询对象。
    """

    objection_id: int
    objector_id: int
    objection_reason: str
    proposal_id: int
    proposal_title: str
    proposal_thread_id: int
    guild_id: int
