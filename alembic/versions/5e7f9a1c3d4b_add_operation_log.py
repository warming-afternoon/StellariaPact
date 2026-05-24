"""Add operation_log table

Revision ID: 5e7f9a1c3d4b
Revises: 4d6e8f0a1b2c
Create Date: 2026-05-24 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5e7f9a1c3d4b"
down_revision: Union[str, Sequence[str], None] = "4d6e8f0a1b2c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "operation_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("operator_id", sa.Integer(), nullable=False, index=True),
        sa.Column("operator_name", sa.String(), nullable=False),
        sa.Column("operator_display_name", sa.String(), nullable=False),
        sa.Column("op_type", sa.Integer(), nullable=False, index=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False, index=True),
        sa.Column("target_id", sa.Integer(), nullable=False, index=True),
        sa.Column("guild_id", sa.Integer(), nullable=False, index=True),
        sa.Column("detail", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("operation_log")
