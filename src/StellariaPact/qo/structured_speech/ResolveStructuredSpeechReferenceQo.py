from StellariaPact.share import BaseDto


class ResolveStructuredSpeechReferenceQo(BaseDto):
    """封装解析右键回复目标用户所需的消息元数据。"""

    message_id: int
    """表示被右键选择的 Discord 消息 ID。"""

    author_id: int
    """表示 Discord 返回的消息作者 ID。"""

    author_is_bot: bool
    """表示 Discord 返回的消息作者是否为 Bot。"""

    webhook_id: int | None
    """表示消息对应的 Webhook ID，普通成员消息为空。"""
