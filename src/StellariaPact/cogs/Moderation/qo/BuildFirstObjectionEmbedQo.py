from ....share.BaseDto import BaseDto


class BuildFirstObjectionEmbedQo(BaseDto):
    """
    用于构建首次异议 Embed 的数据查询对象。
    """

    proposal_title: str
    proposal_url: str
    objector_id: int
    objector_display_name: str
    objection_reason: str
    required_votes: int
