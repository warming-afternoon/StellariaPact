from StellariaPact.share import BaseDto


class DeleteStructuredSpeechMessagesQo(BaseDto):
    """封装一批待回滚的结构化消息 ID。"""

    message_ids: set[int]
