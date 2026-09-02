from StellariaPact.share import BaseDto


class EnableStructuredSpeechModeQo(BaseDto):
    """封装开启或更新模板发言模式所需的数据。"""

    operator_id: int
    interval_seconds: int | None = None
    proposer_cooldown_exempt: bool | None = None
