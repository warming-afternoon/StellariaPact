import logging
import os
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# --- 初始化 ---
load_dotenv()
logger = logging.getLogger("stellaria_pact.database")


class DatabaseHandler:
    """
    数据库处理程序
    负责数据库的初始化、连接和会话管理。
    这个类的实例应该被视为一个单例，通过 initialize_db_handler 和 get_db_handler 进行管理。
    """

    def __init__(self):
        self._async_engine = None
        self._initialized = False

    def initialize(self):
        """
        执行实际的初始化，设置数据库引擎。
        这个方法应该只被调用一次。
        """
        if self._initialized:
            logger.warning("DatabaseHandler 已经初始化，跳过重复初始化。")
            return

        logger.info("正在初始化 DatabaseHandler...")

        db_name = os.getenv("DATABASE_NAME", "data/database.db")
        db_dir = os.path.dirname(db_name)
        if db_dir and not os.path.exists(db_dir):
            logger.info(f"数据库目录 '{db_dir}' 不存在，正在创建...")
            os.makedirs(db_dir)

        sqlite_url = f"sqlite+aiosqlite:///{db_name}"
        connect_args = {"timeout": 15}

        sql_echo_str = os.getenv("SQL_ECHO", "False")
        sql_echo = sql_echo_str.lower() in ("true", "1", "t")

        self._async_engine = create_async_engine(
            sqlite_url, echo=sql_echo, connect_args=connect_args
        )

        @event.listens_for(self._async_engine.sync_engine, "connect")
        def _enable_wal(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
            finally:
                cursor.close()

        self._initialized = True
        logger.info("DatabaseHandler 初始化完成。")

    async def init_db(self):
        """
        初始化数据库，创建所有定义的表 (包含索引)。
        """
        if not self._initialized or not self._async_engine:
            raise RuntimeError("DatabaseHandler 尚未初始化。请先调用 initialize_db_handler。")

        # logger.info("正在检查并创建数据库表...")
        async with self._async_engine.begin() as conn:
            # logger.info(f"元数据中已注册的表: {SQLModel.metadata.tables.keys()}")
            await conn.run_sync(SQLModel.metadata.create_all)
        # logger.info("数据库表检查与创建完成。")

    def get_session(self) -> AsyncSession:
        """
        创建一个新的异步数据库会话实例。
        """
        if not self._initialized or not self._async_engine:
            raise RuntimeError("DatabaseHandler 尚未初始化。请先调用 initialize_db_handler。")
        return AsyncSession(self._async_engine)


# --- 单例管理 ---

_db_handler_instance: Optional[DatabaseHandler] = None


def initialize_db_handler() -> DatabaseHandler:
    """
    创建并初始化 DatabaseHandler 的单例实例。
    """
    global _db_handler_instance
    if _db_handler_instance is None:
        _db_handler_instance = DatabaseHandler()
        _db_handler_instance.initialize()
    return _db_handler_instance


def get_db_handler() -> DatabaseHandler:
    """
    获取 DatabaseHandler 的单例实例。
    如果实例尚未初始化，将引发 RuntimeError。
    """
    if _db_handler_instance is None:
        raise RuntimeError(
            "DatabaseHandler 实例尚未创建。请确保在程序启动时调用了 initialize_db_handler。"
        )
    return _db_handler_instance
