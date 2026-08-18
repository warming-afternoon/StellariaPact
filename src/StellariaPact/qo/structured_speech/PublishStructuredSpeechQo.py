from StellariaPact.share import BaseDto


class PublishStructuredSpeechQo(BaseDto):
    """封装一次结构化发言的业务数据。"""

    guild_id: int
    thread_id: int
    user_id: int
    content: str
    cooldown_exempt: bool
