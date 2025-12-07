from typing import Optional

from StellariaPact.dto.ObjectionDto import ObjectionDto
from StellariaPact.dto.ProposalDto import ProposalDto
from StellariaPact.share.BaseDto import BaseDto


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
