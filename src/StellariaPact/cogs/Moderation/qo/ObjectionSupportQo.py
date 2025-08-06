from typing import Literal

from pydantic import BaseModel, Field


class ObjectionSupportQo(BaseModel):
    """
    用于处理用户在“异议产生票收集”阶段行为的查询对象。
    """

    userId: int = Field(..., description="执行操作的用户的Discord ID。")
    messageId: int = Field(..., description="包含投票面板的消息的ID。")
    action: Literal["support", "withdraw"] = Field(
        ...,
        description="用户执行的具体操作，'support'（支持）或 'withdraw'（撤回）。",
    )
