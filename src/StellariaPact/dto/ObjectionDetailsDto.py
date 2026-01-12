from StellariaPact.share.BaseDto import BaseDto


class ObjectionDetailsDto(BaseDto):
    """
    封装了异议及其关联提案的详细信息，用于在服务层和逻辑层之间传递数据。
    """

    # --- Objection Fields ---
    objection_id: int
    """异议ID"""

    objection_reason: str
    """反对理由"""

    objector_id: int
    """异议发起人的Discord ID"""

    # --- Proposal Fields ---
    proposal_id: int
    """提案ID"""

    proposal_title: str
    """提案标题"""
