from typing import Literal

from StellariaPact.share.BaseDto import BaseDto


class UpdateUserActivityQo(BaseDto):
    """
    用于更新用户活动（增/减发言计数）的QO。
    """

    user_id: int
    thread_id: int
    change: Literal[1, -1]
