import logging
import os


class LoggingConfigurator:
    """
    一个用于集中配置项目日志记录器的类。
    """

    def __init__(self, rootLogLevel: str = "INFO"):
        """
        初始化配置器。
        :param rootLogLevel: 从 .env 文件读取的根日志级别字符串。
        """
        self.logLevel = getattr(logging, rootLogLevel.upper(), logging.INFO)
        self.formatter = logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s")
        self.streamHandler = logging.StreamHandler()
        self.streamHandler.setFormatter(self.formatter)

    def configure(self):
        """
        应用所有日志配置。
        """
        self._configureRootLogger()
        self._configureSqlAlchemyLogger()
        self._configureDiscordLogger()
        logging.getLogger(__name__).info("日志记录器配置完成。")

    def _configureRootLogger(self):
        """配置根日志记录器，这是我们自己代码的基础。"""
        # 在新版 logging 中，建议配置一个包级别的 logger，而不是 root logger
        logger = logging.getLogger("stellaria_pact")
        logger.setLevel(self.logLevel)
        if not logger.handlers:
            logger.addHandler(self.streamHandler)
        logger.propagate = False

    def _configureSqlAlchemyLogger(self):
        """配置 SQLAlchemy 的日志记录器。"""
        # 从环境变量获取 SQLAlchemy 的日志级别，默认为 WARNING
        log_level_str = os.getenv("SQLALCHEMY_LOG_LEVEL", "WARNING").upper()
        log_level = getattr(logging, log_level_str, logging.WARNING)

        sql_logger = logging.getLogger("sqlalchemy.engine")
        sql_logger.setLevel(log_level)
        if not sql_logger.handlers:
            sql_logger.addHandler(self.streamHandler)
        sql_logger.propagate = False

    def _configureDiscordLogger(self):
        """配置 discord.py 的日志记录器，以便捕获其内部错误。"""
        discord_logger = logging.getLogger("discord")
        # discord.py 的日志级别设置为 INFO
        discord_logger.setLevel(logging.DEBUG)
        if not discord_logger.handlers:
            discord_logger.addHandler(self.streamHandler)
        discord_logger.propagate = False
