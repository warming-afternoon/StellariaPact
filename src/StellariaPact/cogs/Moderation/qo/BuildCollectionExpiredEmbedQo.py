from pydantic import BaseModel, Field


class BuildCollectionExpiredEmbedQo(BaseModel):
    """
    构建异议支持票收集到期 Embed 的查询对象。
    """

    proposal_title: str = Field(..., description="相关的提案标题")
    proposal_url: str = Field(..., description="相关的提案链接")
    objector_id: int = Field(..., description="异议发起人ID")
    objector_display_name: str = Field(..., description="异议发起人显示名称")
    objection_reason: str = Field(..., description="相关的异议理由")
    final_votes: int = Field(..., description="最终支持票数")
    required_votes: int = Field(..., description="所需支持票数")
