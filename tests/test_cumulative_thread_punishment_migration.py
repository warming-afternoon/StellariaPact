import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text


def test_cumulative_migration_backfills_and_downgrades_without_losing_history():
    """覆盖旧歪楼滑坡、无实际处罚、禁言和剥夺投票权四类记录。"""
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "alembic"))
        url = f"sqlite:///{(Path(directory) / 'migration.db').as_posix()}"
        config.set_main_option("sqlalchemy.url", url)
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "CREATE TABLE punishment_record ("
                    "id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL, "
                    "thread_id INTEGER NOT NULL, "
                    "target_user_id INTEGER NOT NULL, moderator_id INTEGER NOT NULL, "
                    "reason VARCHAR NOT NULL, source_message_url VARCHAR, "
                    "voting_allowed BOOLEAN NOT NULL, mute_end_time DATETIME, "
                    "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                    "publicity_guild_id INTEGER, publicity_channel_id INTEGER, "
                    "publicity_message_id INTEGER)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO punishment_record "
                    "(id,guild_id,thread_id,target_user_id,moderator_id,reason,"
                    "voting_allowed,mute_end_time) "
                    "VALUES (:id,1,10,20,30,:reason,:voting,:mute)"
                ),
                [
                    dict(id=1, reason="请不要歪楼滑坡", voting=1, mute="2025-01-01 00:00:00"),
                    dict(id=2, reason="旧禁言", voting=1, mute="2025-01-01 00:00:00"),
                    dict(id=3, reason="剥夺投票权", voting=0, mute=None),
                    dict(id=4, reason="无实际处罚", voting=1, mute=None),
                ],
            )
        engine.dispose()
        command.stamp(config, "08b1d3f5a7c9")
        assert ScriptDirectory.from_config(config).get_heads() == ["a8b0d2e4f6c1"]
        command.upgrade(config, "head")
        engine = create_engine(url)
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT counts_toward_cumulative, lifted_at, lifted_by_id, lift_reason, "
                    "source_publicity_message_id FROM punishment_record ORDER BY id"
                )
            ).all()
        assert [bool(row[0]) for row in rows] == [False, True, True, False]
        assert all(tuple(row[1:]) == (None, None, None, None) for row in rows)
        engine.dispose()
        command.downgrade(config, "08b1d3f5a7c9")
        engine = create_engine(url)
        assert "counts_toward_cumulative" not in {
            column["name"] for column in inspect(engine).get_columns("punishment_record")
        }
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT count(*) FROM punishment_record")).scalar_one()
                == 4
            )
        engine.dispose()
