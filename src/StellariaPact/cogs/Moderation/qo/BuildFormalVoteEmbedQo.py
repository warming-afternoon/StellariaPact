from pydantic import BaseModel, Field


class BuildFormalVoteEmbedQo(BaseModel):
    """
    构建正式异议投票 Embed 的查询对象。
    """

    proposal_title: str = Field(..., description="提案标题")
    proposal_thread_url: str = Field(..., description="提案讨论帖链接")
    objection_id: int = Field(..., description="异议ID")
    objector_id: int = Field(..., description="异议发起人ID")
    objection_reason: str = Field(..., description="异议理由")