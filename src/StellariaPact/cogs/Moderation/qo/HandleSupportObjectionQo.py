from ....share.BaseDto import BaseDto


class HandleSupportObjectionQo(BaseDto):
    """
    处理“支持异议”操作的查询对象。
    """

    user_id: int
    message_id: int
