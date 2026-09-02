import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_thread_punishment_publicity_migration_round_trip() -> None:
    """验证豁免默认值、公示位置字段和已有数据的升级降级。"""
    project_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as temporary_directory:
        database_path = Path(temporary_directory) / "migration.db"
        database_url = f"sqlite:///{database_path.as_posix()}"
        config = Config(str(project_root / "alembic.ini"))
        config.set_main_option("script_location", str(project_root / "alembic"))
        config.set_main_option("sqlalchemy.url", database_url)

        engine = create_engine(database_url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE structured_speech_mode ("
                    "id INTEGER NOT NULL PRIMARY KEY, guild_id INTEGER NOT NULL, "
                    "forum_id INTEGER NOT NULL, thread_id INTEGER NOT NULL, "
                    "status VARCHAR(16) NOT NULL, interval_seconds INTEGER NOT NULL, "
                    "previous_slowmode_delay INTEGER NOT NULL, enabled_by_id INTEGER NOT NULL, "
                    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, "
                    "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE punishment_record ("
                    "id INTEGER NOT NULL PRIMARY KEY, guild_id INTEGER NOT NULL, "
                    "thread_id INTEGER NOT NULL, target_user_id INTEGER NOT NULL, "
                    "moderator_id INTEGER NOT NULL, reason VARCHAR NOT NULL, "
                    "source_message_url VARCHAR, voting_allowed BOOLEAN NOT NULL, "
                    "mute_end_time DATETIME, "
                    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO structured_speech_mode "
                    "(id, guild_id, forum_id, thread_id, status, interval_seconds, "
                    "previous_slowmode_delay, enabled_by_id) "
                    "VALUES (1, 10, 20, 30, 'active', 120, 0, 40)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO punishment_record "
                    "(id, guild_id, thread_id, target_user_id, moderator_id, reason, "
                    "voting_allowed) VALUES (1, 10, 30, 50, 40, '迁移前记录', 0)"
                )
            )
        engine.dispose()
        command.stamp(config, "e6b8c1d4f2a0")

        command.upgrade(config, "head")
        engine = create_engine(database_url)
        inspector = inspect(engine)
        assert {
            "publicity_guild_id",
            "publicity_channel_id",
            "publicity_message_id",
        }.issubset({column["name"] for column in inspector.get_columns("punishment_record")})
        with engine.connect() as connection:
            exempt = connection.execute(
                text(
                    "SELECT proposer_cooldown_exempt FROM structured_speech_mode WHERE id = 1"
                )
            ).scalar_one()
            reason = connection.execute(
                text("SELECT reason FROM punishment_record WHERE id = 1")
            ).scalar_one()
        assert bool(exempt) is True
        assert reason == "迁移前记录"
        engine.dispose()

        command.downgrade(config, "e6b8c1d4f2a0")
        engine = create_engine(database_url)
        inspector = inspect(engine)
        assert "proposer_cooldown_exempt" not in {
            column["name"] for column in inspector.get_columns("structured_speech_mode")
        }
        assert not {
            "publicity_guild_id",
            "publicity_channel_id",
            "publicity_message_id",
        }.intersection({column["name"] for column in inspector.get_columns("punishment_record")})
        engine.dispose()
