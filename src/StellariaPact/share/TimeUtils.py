import logging
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


class TimeUtils:
    """
    一个用于处理时间相关操作的工具类。
    """

    @staticmethod
    def get_utc_end_time(
        duration_hours: int, start_time: datetime | None = None
    ) -> datetime:
        """
        根据持续时间计算出未来的、准确的 UTC 结束时间。
        
        Args:
            duration_hours: 持续的小时数。
            start_time: 计算的起始时间。如果为 None，则使用当前 UTC 时间。

        Returns:
            一个代表未来准确结束时间的、带时区的 UTC datetime 对象。
        """
        # 统一使用带时区的 UTC 时间
        now_utc = start_time if start_time else datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)

        # 直接在 UTC 上加上持续时间，安全且简单
        return now_utc + timedelta(hours=duration_hours)

    @staticmethod
    def parse_discord_timestamp(content: str) -> datetime | None:
        """
        从消息内容中解析 Discord 的截止时间戳。
        截止时间格式为"截止时间: <t:UNIX时间戳:F>"
        """
        match = re.search(r"截止时间[:：\s*]*<[tT]:(\d+):[fF]>", content)
        if match:
            timestamp = int(match.group(1))
            # 直接返回带有 UTC 时区信息的 datetime 对象
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        return None
