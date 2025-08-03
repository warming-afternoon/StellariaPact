from dataclasses import dataclass
from typing import Dict, List


@dataclass
class ConfirmationSessionDto:
    """
    用于在事务边界之间安全传递确认会话数据的数据传输对象。
    """

    id: int
    status: int
    canceler_id: int | None
    confirmed_parties: Dict[str, int]
    required_roles: List[str]
