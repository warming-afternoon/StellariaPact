from typing import Optional

from ....share.BaseDto import BaseDto
from .ObjectionDto import ObjectionDto
from .ProposalDto import ProposalDto


class ObjectionReviewResultDto(BaseDto):
    """
    封装异议审核操作（批准/驳回）的结果。
    """

    success: bool
    message: str
    objection: Optional[ObjectionDto] = None
    proposal: Optional[ProposalDto] = None
    moderator_id: Optional[int] = None
    reason: Optional[str] = None
    is_approve: Optional[bool] = None
