from typing import Dict

from ....share.BaseDto import BaseDto
from .ConfirmationSessionDto import ConfirmationSessionDto


class ExecuteProposalResultDto(BaseDto):
    """
    用于封装 handle_execute_proposal 逻辑层方法成功执行后的结果。
    """

    session_dto: ConfirmationSessionDto
    role_display_names: Dict[str, str]
    channel_id: int
    guild_id: int
