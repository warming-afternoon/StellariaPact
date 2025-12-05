from dataclasses import dataclass
from datetime import datetime


@dataclass
class AdjustTimeDto:
    """
    数据传输对象，用于封装修改公示时间的结果。
    """

    announcement_id: int
    old_end_time: datetime
    new_end_time: datetime
