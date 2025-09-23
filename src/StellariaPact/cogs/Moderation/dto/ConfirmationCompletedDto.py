from typing import Optional

from StellariaPact.share.BaseDto import BaseDto


class ConfirmationSessionDto(BaseDto):
    """
    复制了ConfirmationSession模型的核心数据，以避免在事务外访问延迟加载的属性。
    """

    id: int
    context: str
    targetId: int
    messageId: int
    requiredRoles: list[str]
    confirmedParties: Optional[dict[str, int]] = None
    status: int
    cancelerId: Optional[int] = None
