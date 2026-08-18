import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_structured_speech_migration_round_trip() -> None:
    """验证模板发言的两张表和索引能够升级并完整降级。"""
    project_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite:///{database_path.as_posix()}"
        config = Config(str(project_root / "alembic.ini"))
        config.set_main_option("script_location", str(project_root / "alembic"))
        config.set_main_option("sqlalchemy.url", database_url)

        command.stamp(config, "d5a7c9e1f3b6")
        command.upgrade(config, "head")

        engine = create_engine(database_url)
        inspector = inspect(engine)
        assert {
            "structured_speech_mode",
            "structured_speech_message",
        }.issubset(inspector.get_table_names())
        assert {index["name"] for index in inspector.get_indexes("structured_speech_message")} == {
            "ix_structured_speech_message_webhook",
            "ix_structured_speech_message_thread_user_created",
            "uq_structured_speech_message_discord",
        }
        engine.dispose()

        command.downgrade(config, "d5a7c9e1f3b6")
        engine = create_engine(database_url)
        table_names = inspect(engine).get_table_names()
        assert "structured_speech_mode" not in table_names
        assert "structured_speech_message" not in table_names
        engine.dispose()
