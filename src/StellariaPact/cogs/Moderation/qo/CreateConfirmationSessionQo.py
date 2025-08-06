from typing import List

from ....share.BaseDto import BaseDto


class CreateConfirmationSessionQo(BaseDto):
    """
    用于创建确认会话的查询对象。
    """

    context: str
    target_id: int
    required_roles: List[str]
    initiator_id: int
    initiator_role_keys: List[str]
    message_id: int | None = None
