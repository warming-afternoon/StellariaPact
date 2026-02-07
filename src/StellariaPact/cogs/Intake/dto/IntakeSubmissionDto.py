from pydantic import BaseModel, Field


class IntakeSubmissionDto(BaseModel):
    """
    草案提交的数据传输对象
    """

    author_id: int = Field(..., description="提交者用户ID")
    """提交者用户ID"""

    guild_id: int = Field(..., description="服务器ID")
    """服务器ID"""

    title: str = Field(..., max_length=100, description="提案标题")
    """提案标题"""

    reason: str = Field(..., max_length=1000, description="提案原因")
    """提案原因"""

    motion: str = Field(..., max_length=500, description="动议内容")
    """动议内容"""

    implementation: str = Field(..., max_length=1000, description="实施方案")
    """实施方案"""

    executor: str = Field(..., max_length=100, description="执行人")
    """执行人"""
