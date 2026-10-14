from datetime import datetime, timezone

# 复用现有禁言截止时间字段，所有展示入口统一识别永久禁言。
PERMANENT_THREAD_MUTE = datetime.max.replace(tzinfo=timezone.utc)
OFF_TOPIC_REASON = "请不要歪楼滑坡"


def chinese_number(number: int, *, leading: bool = True) -> str:
    """将正整数转换为处罚理由使用的中文数字。"""
    digits = "零一二三四五六七八九"
    if number < 10:
        return digits[number]
    for value, unit in ((100000000, "亿"), (10000, "万"), (1000, "千"), (100, "百"), (10, "十")):
        if number >= value:
            quotient, remainder = divmod(number, value)
            prefix = "" if value == 10 and quotient == 1 and leading else chinese_number(quotient)
            suffix = ""
            if remainder:
                suffix = ("零" if remainder < value // 10 else "") + chinese_number(
                    remainder, leading=False
                )
            return prefix + unit + suffix
    raise ValueError("处罚次数必须是非负整数。")


def format_thread_mute(mute_end_time: datetime | None) -> str:
    """统一格式化帖子内禁言状态，避免渲染永久禁言的极大日期。"""
    if mute_end_time == PERMANENT_THREAD_MUTE:
        return "永久禁言"
    if mute_end_time is None:
        return "未禁言"
    timestamp = int(mute_end_time.timestamp())
    return f"禁言至 <t:{timestamp}:F> (<t:{timestamp}:R>)"
