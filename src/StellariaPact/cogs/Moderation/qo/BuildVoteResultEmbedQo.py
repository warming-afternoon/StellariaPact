from pydantic import BaseModel, Field


class BuildVoteResultEmbedQo(BaseModel):
    """
    构建异议投票结果 Embed 的查询对象。
    """

    proposal_title: str = Field(..., description="相关的提案标题")
    proposal_thread_url: str = Field(..., description="相关的提案链接")
    objection_id: int = Field(..., description="相关的异议ID")
    objection_reason: str = Field(..., description="相关的异议理由")
    is_passed: bool = Field(..., description="投票是否通过")
    approve_votes: int = Field(..., description="赞成票数")
    reject_votes: int = Field(..., description="反对票数")
    total_votes: int = Field(..., description="总票数")
