from typing import Literal

from StellariaPact.share import BaseDto


class ModeChangeResultDto(BaseDto):
    """表示模板发言模式切换后的结果。"""

    action: Literal["enabled", "updated", "disabled", "unchanged"]
    """表示本次模式切换实际执行的操作。"""

    interval_seconds: int | None = None
    """表示切换完成后的用户发言间隔秒数。"""

    proposer_cooldown_exempt: bool | None = None
    """表示切换完成后提案主是否豁免发言间隔。"""
