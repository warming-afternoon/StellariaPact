from StellariaPact.qo.structured_speech import ResolveStructuredSpeechReferenceQo
from StellariaPact.share import StellariaPactBot, UnitOfWork

from .StructuredSpeechUserError import StructuredSpeechUserError


class StructuredSpeechMessageTargetResolver:
    """解析普通消息或结构化 Webhook 消息对应的真实用户。"""

    def __init__(self, bot: StellariaPactBot):
        """保存数据库访问所需的 Bot 实例。"""
        self.bot = bot

    async def resolve_user_id(self, qo: ResolveStructuredSpeechReferenceQo) -> int:
        """根据消息元数据返回真实用户 ID。"""
        # Webhook 消息必须存在结构化发言记录，不能推测第三方 Webhook 的身份。
        if qo.webhook_id is not None:
            async with UnitOfWork(self.bot.db_handler) as uow:
                user_id = await uow.structured_speech_message.get_original_user_id(qo.message_id)
            if user_id is None:
                raise StructuredSpeechUserError("无法识别这条 Webhook 消息的原发言者。")
            return user_id

        # Bot 原生消息没有可还原的普通成员身份。
        if qo.author_is_bot:
            raise StructuredSpeechUserError("不能选择 Bot 消息执行此操作。")
        return qo.author_id
