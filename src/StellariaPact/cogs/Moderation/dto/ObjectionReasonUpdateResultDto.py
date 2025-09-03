from typing import Optional

from StellariaPact.share.BaseDto import BaseDto


class ObjectionReasonUpdateResultDto(BaseDto):
    """
    用于从 ModerationLogic 返回更新结果的数据传输对象。
    包含了更新审核帖子 Embed 所需的所有信息。
    """

    success: bool
    message: str
    guild_id: Optional[int] = None
    review_thread_id: Optional[int] = None
    objection_id: Optional[int] = None
    proposal_id: Optional[int] = None
    proposal_title: Optional[str] = None
    proposal_thread_id: Optional[int] = None
    objector_id: Optional[int] = None
    new_reason: Optional[str] = None
