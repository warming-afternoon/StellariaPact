import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger("stellaria_pact.time_utils")


class TimeUtils:
    """
    一个用于处理时间相关操作的工具类。
    """

    @staticmethod
    def get_utc_end_time(
        duration_hours: int, target_tz: str, start_time: datetime | None = None
    ) -> datetime:
        """
        根据本地时区的持续时间计算出未来的、准确的 UTC 结束时间。

        Args:
            duration_hours: 持续的小时数。
            target_tz: 目标时区的 IANA 名称，例如 "Asia/Shanghai"。
            start_time: 计算的起始时间（带时区的 UTC datetime）。如果为 None，则使用当前时间。

        Returns:
            一个代表未来准确结束时间的、朴素的 UTC datetime 对象。

        Raises:
            Exception: 如果在转换过程中发生错误，则重新抛出。
        """
        try:
            # 如果未提供起始时间，则获取当前带时区信息的 UTC 时间
            now_utc = start_time if start_time else datetime.now(ZoneInfo("UTC"))

            # 转换为目标本地时区
            try:
                target_zone = ZoneInfo(target_tz)
            except ZoneInfoNotFoundError:
                logger.warning(f"无效的时区 '{target_tz}'。将回退到 UTC。")
                target_zone = ZoneInfo("UTC")

            now_local = now_utc.astimezone(target_zone)

            # 在本地时区下计算结束时间
            end_time_local = now_local + timedelta(hours=duration_hours)

            # 将本地结束时间转换回 UTC
            end_time_utc = end_time_local.astimezone(ZoneInfo("UTC"))

            # 返回一个不含时区信息的 "naive" datetime 对象，以便存入数据库
            return end_time_utc.replace(tzinfo=None)

        except Exception as e:
            logger.exception("在计算 UTC 结束时间时发生未知错误。")
            raise e

    @staticmethod
    def parse_discord_timestamp(content: str) -> datetime | None:
        """
        从消息内容中解析 Discord 的截止时间戳。
        截止时间格式为"截止时间: <t:UNIX时间戳:F>"
        """
        match = re.search(r"截止时间[:：\s*]*<[tT]:(\d+):[fF]>", content)
        if match:
            timestamp = int(match.group(1))
            # 返回一个不含时区信息的 "naive" datetime 对象
            return datetime.fromtimestamp(timestamp, tz=ZoneInfo("UTC")).replace(tzinfo=None)
        return None
