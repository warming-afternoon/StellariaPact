import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

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
    数据库处理程序 (单例模式)
    负责数据库的初始化、连接和会话管理。
    """

    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        logger.info("正在初始化 DatabaseHandler...")

        db_name = os.getenv("DATABASE_NAME", "data/database.db")
        db_dir = os.path.dirname(db_name)
        if db_dir and not os.path.exists(db_dir):
            logger.info(f"数据库目录 '{db_dir}' 不存在，正在创建...")
            os.makedirs(db_dir)

        sqlite_url = f"sqlite+aiosqlite:///{db_name}"
        connect_args = {"timeout": 15}

        self._async_engine = create_async_engine(sqlite_url, echo=True, connect_args=connect_args)

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
        logger.info("正在检查并创建数据库表...")
        async with self._async_engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        logger.info("数据库表检查与创建完成。")

    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        提供一个异步数据库会话的上下文管理器。
        """
        async with AsyncSession(self._async_engine) as session:
            yield session


# 创建一个单例实例供全局使用
db_handler = DatabaseHandler()
