from dataclasses import dataclass
from typing import Dict, List


@dataclass
class ConfirmationEmbedData:
    """
    用于构建确认流程 Embed 的数据传输对象。
    """

    status: int
    canceler_id: int | None
    confirmed_parties: Dict[str, int]
    required_roles: List[str]