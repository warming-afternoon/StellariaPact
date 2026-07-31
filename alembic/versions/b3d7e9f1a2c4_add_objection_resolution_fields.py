"""add objection resolution fields

Revision ID: b3d7e9f1a2c4
Revises: 9f2b4c6d8e0a
Create Date: 2026-07-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3d7e9f1a2c4"
down_revision: Union[str, Sequence[str], None] = "9f2b4c6d8e0a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("vote_option", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "resolution_type",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )
        batch_op.add_column(
            sa.Column("resolution_description", sa.String(), nullable=True)
        )

    with op.batch_alter_table("confirmation_session", schema=None) as batch_op:
        batch_op.add_column(sa.Column("payload", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("confirmation_session", schema=None) as batch_op:
        batch_op.drop_column("payload")

    with op.batch_alter_table("vote_option", schema=None) as batch_op:
        batch_op.drop_column("resolution_description")
        batch_op.drop_column("resolution_type")
