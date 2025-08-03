from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class CreateConfirmationSessionQo:
    """
    用于创建确认会话的查询对象。
    """

    context: str
    target_id: int
    required_roles: List[str]
    initiator_id: int
    initiator_role_keys: List[str]
    message_id: int | None = None
