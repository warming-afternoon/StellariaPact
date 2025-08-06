from ....share.BaseDto import BaseDto
from ....share.enums.ProposalStatus import ProposalStatus


class ProposalDto(BaseDto):
    """
    提案的数据传输对象
    """

    id: int
    title: str
    status: ProposalStatus
    discussionThreadId: int | None
