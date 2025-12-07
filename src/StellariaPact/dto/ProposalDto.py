from StellariaPact.share.BaseDto import BaseDto

from ..share.enums.ProposalStatus import ProposalStatus


class ProposalDto(BaseDto):
    """
    提案的数据传输对象
    """

    id: int
    proposer_id: int
    title: str
    content: str
    status: ProposalStatus
    discussion_thread_id: int | None
