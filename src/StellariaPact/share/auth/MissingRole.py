from discord.app_commands import AppCommandError


class MissingRole(AppCommandError):
    """
    当用户缺少执行命令所需的身份组时抛出的异常。
    """

    def __init__(self, message: str = "抱歉，你没有权限执行此操作。"):
        """
        初始化 MissingRole 异常。

        Args:
            message (str, optional): 显示给用户的错误消息。默认为 "抱歉，你没有权限执行此操作。"。
        """
        super().__init__(message)
