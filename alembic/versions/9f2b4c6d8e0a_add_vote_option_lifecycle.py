"""Add vote option lifecycle fields

Revision ID: 9f2b4c6d8e0a
Revises: 8e1a2b3c4d5f
Create Date: 2026-07-18 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "9f2b4c6d8e0a"
down_revision: Union[str, Sequence[str], None] = "8e1a2b3c4d5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("vote_option", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("voting_status", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(sa.Column("closed_at", sa.DateTime(), nullable=True))
        batch_op.create_index(
            op.f("ix_vote_option_voting_status"), ["voting_status"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("vote_option", schema=None) as batch_op:
        batch_op.drop_index(op.f("ix_vote_option_voting_status"))
        batch_op.drop_column("closed_at")
        batch_op.drop_column("voting_status")
