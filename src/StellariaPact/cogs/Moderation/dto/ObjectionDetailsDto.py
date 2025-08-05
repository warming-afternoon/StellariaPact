from ....share.BaseDto import BaseDto


class ObjectionDetailsDto(BaseDto):
    """
    封装了异议及其关联提案的详细信息，用于在服务层和逻辑层之间传递数据。
    """

    # --- Objection Fields ---
    objection_id: int
    objection_reason: str
    objector_id: int

    # --- Proposal Fields ---
    proposal_id: int
    proposal_title: str
