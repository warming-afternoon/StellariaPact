"""Add punishment_record table

Revision ID: 7c9d2e4f6a8b
Revises: 5e7f9a1c3d4b
Create Date: 2026-07-07 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7c9d2e4f6a8b"
down_revision: Union[str, Sequence[str], None] = "5e7f9a1c3d4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 检查表是否已存在（可能已被 SQLModel.metadata.create_all() 创建）
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "punishment_record" in inspector.get_table_names():
        return
    op.create_table(
        "punishment_record",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=False),
        sa.Column("moderator_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("source_message_url", sa.String(), nullable=True),
        sa.Column("voting_allowed", sa.Boolean(), nullable=False),
        sa.Column("mute_end_time", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_punishment_record_guild_id", "punishment_record", ["guild_id"], unique=False
    )
    op.create_index(
        "ix_punishment_record_moderator_id",
        "punishment_record",
        ["moderator_id"],
        unique=False,
    )
    op.create_index(
        "ix_punishment_record_thread_user_created",
        "punishment_record",
        ["thread_id", "target_user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_punishment_record_thread_user_created", table_name="punishment_record")
    op.drop_index("ix_punishment_record_moderator_id", table_name="punishment_record")
    op.drop_index("ix_punishment_record_guild_id", table_name="punishment_record")
    op.drop_table("punishment_record")
