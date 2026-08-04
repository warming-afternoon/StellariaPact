import tempfile
import unittest
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


class GlobalPunishmentMessageMigrationTests(unittest.TestCase):
    """验证处罚公示消息位置迁移可以安全升级和降级。"""

    def test_migration_preserves_old_records_and_round_trips(self) -> None:
        """新增四个可空字段时应保留旧记录，降级后应完整移除字段。"""
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
                        "CREATE TABLE global_proposal_punishment ("
                        "id INTEGER NOT NULL PRIMARY KEY, "
                        "target_user_id INTEGER NOT NULL, "
                        "moderator_id INTEGER NOT NULL, "
                        "origin_guild_id INTEGER NOT NULL, "
                        "origin_channel_id INTEGER NOT NULL, "
                        "punishment_type VARCHAR NOT NULL, "
                        "reason VARCHAR NOT NULL, "
                        "evidence_url VARCHAR, evidence_filename VARCHAR, "
                        "created_at DATETIME NOT NULL, expires_at DATETIME, "
                        "lifted_by_id INTEGER, lift_reason VARCHAR, lifted_at DATETIME"
                        ")"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO global_proposal_punishment "
                        "(id, target_user_id, moderator_id, origin_guild_id, "
                        "origin_channel_id, punishment_type, reason, created_at) "
                        "VALUES (1, 10, 20, 30, 40, 'permanent_voting', "
                        "'迁移前记录', CURRENT_TIMESTAMP)"
                    )
                )
            engine.dispose()
            command.stamp(config, "c4e8a1f3b6d2")

            command.upgrade(config, "head")
            engine = create_engine(database_url)
            upgraded_columns = {
                column["name"]
                for column in inspect(engine).get_columns("global_proposal_punishment")
            }
            self.assertTrue(
                {
                    "punishment_message_id",
                    "resolution_guild_id",
                    "resolution_channel_id",
                    "resolution_message_id",
                }.issubset(upgraded_columns)
            )
            with engine.connect() as connection:
                reason = connection.execute(
                    text("SELECT reason FROM global_proposal_punishment WHERE id = 1")
                ).scalar_one()
            self.assertEqual(reason, "迁移前记录")

            engine.dispose()
            command.downgrade(config, "c4e8a1f3b6d2")
            engine = create_engine(database_url)
            downgraded_columns = {
                column["name"]
                for column in inspect(engine).get_columns("global_proposal_punishment")
            }
            self.assertNotIn("punishment_message_id", downgraded_columns)
            self.assertNotIn("resolution_guild_id", downgraded_columns)
            self.assertNotIn("resolution_channel_id", downgraded_columns)
            self.assertNotIn("resolution_message_id", downgraded_columns)
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
