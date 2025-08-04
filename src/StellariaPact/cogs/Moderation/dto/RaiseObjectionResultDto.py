from ....share.BaseDto import BaseDto


class RaiseObjectionResultDto(BaseDto):
    """
    用于封装 handle_raise_objection 逻辑层方法成功执行后的结果。
    """

    message: str
    is_first_objection: bool
