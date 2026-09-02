"""Add proposer exemption and thread punishment publicity locations

Revision ID: f7a9c2e4b6d8
Revises: e6b8c1d4f2a0
Create Date: 2026-09-01 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7a9c2e4b6d8"
down_revision: Union[str, Sequence[str], None] = "e6b8c1d4f2a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    table_names = set(sa.inspect(op.get_bind()).get_table_names())
    if "structured_speech_mode" in table_names:
        with op.batch_alter_table("structured_speech_mode") as batch_op:
            batch_op.add_column(
                sa.Column(
                    "proposer_cooldown_exempt",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.true(),
                )
            )

    if "punishment_record" in table_names:
        with op.batch_alter_table("punishment_record") as batch_op:
            batch_op.add_column(sa.Column("publicity_guild_id", sa.Integer(), nullable=True))
            batch_op.add_column(sa.Column("publicity_channel_id", sa.Integer(), nullable=True))
            batch_op.add_column(sa.Column("publicity_message_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    table_names = set(sa.inspect(op.get_bind()).get_table_names())
    if "punishment_record" in table_names:
        with op.batch_alter_table("punishment_record") as batch_op:
            batch_op.drop_column("publicity_message_id")
            batch_op.drop_column("publicity_channel_id")
            batch_op.drop_column("publicity_guild_id")

    if "structured_speech_mode" in table_names:
        with op.batch_alter_table("structured_speech_mode") as batch_op:
            batch_op.drop_column("proposer_cooldown_exempt")
