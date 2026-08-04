"""Add punishment announcement message locations

Revision ID: d5a7c9e1f3b6
Revises: c4e8a1f3b6d2
Create Date: 2026-08-04 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5a7c9e1f3b6"
down_revision: Union[str, Sequence[str], None] = "c4e8a1f3b6d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("global_proposal_punishment") as batch_op:
        batch_op.add_column(sa.Column("punishment_message_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("resolution_guild_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("resolution_channel_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("resolution_message_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("global_proposal_punishment") as batch_op:
        batch_op.drop_column("resolution_message_id")
        batch_op.drop_column("resolution_channel_id")
        batch_op.drop_column("resolution_guild_id")
        batch_op.drop_column("punishment_message_id")
