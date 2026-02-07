from datetime import datetime

from StellariaPact.share import BaseDto


class AnnouncementDto(BaseDto):
    """
    公示的数据传输对象
    """

    id: int
    """主键ID"""

    discussion_thread_id: int
    """关联的Discord讨论帖ID"""

    announcer_id: int
    """公示发起人的Discord ID"""

    title: str
    """公示标题"""

    content: str
    """公示内容"""

    status: int
    """公示状态: 0-已结束, 1-进行中"""

    end_time: datetime
    """公示截止时间"""

    auto_execute: bool
    """公示结束后是否自动进入执行阶段"""
