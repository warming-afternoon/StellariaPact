from StellariaPact.share import BaseDto


class BuildProposalFrozenEmbedQo(BaseDto):
    """
    用于构建提案冻结通知 Embed 的数据查询对象。
    """

    objection_thread_jump_url: str
