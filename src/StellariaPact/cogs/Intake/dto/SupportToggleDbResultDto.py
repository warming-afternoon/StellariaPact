from __future__ import annotations

from StellariaPact.dto.ProposalIntakeDto import ProposalIntakeDto
from StellariaPact.share.BaseDto import BaseDto


class SupportToggleDbResultDto(BaseDto):
    """支持票切换第一阶段（纯 DB 事务）返回结果。"""

    action: str
    """操作类型：supported / withdrawn / already_processed。"""

    count: int
    """当前支持票总数。"""

    intake: ProposalIntakeDto | None
    """用于提交后更新 Discord 面板的数据快照。"""

    need_promote: bool
    """是否需要进入第二阶段立案推进。"""

    intake_id: int | None
    """草案 ID，用于第二阶段重新加锁确认。"""
