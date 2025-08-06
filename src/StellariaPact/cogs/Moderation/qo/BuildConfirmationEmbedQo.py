from typing import Dict, List

from ....share.BaseDto import BaseDto


class BuildConfirmationEmbedQo(BaseDto):
    """
    用于构建确认流程Embed所需的数据查询对象。
    """

    status: int
    canceler_id: int | None
    confirmed_parties: Dict[str, int]
    required_roles: List[str]
    # A map from role key (e.g., "councilModerator") to its display name
    role_display_names: Dict[str, str] = {}
