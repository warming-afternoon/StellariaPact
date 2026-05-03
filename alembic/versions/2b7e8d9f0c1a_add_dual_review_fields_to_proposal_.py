"""add dual-review fields to proposal_intake

Revision ID: 2b7e8d9f0c1a
Revises: 68ae4e95b903
Create Date: 2026-05-03 01:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "2b7e8d9f0c1a"
down_revision: Union[str, Sequence[str], None] = "68ae4e95b903"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("proposal_intake", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("reviewer_id_2", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("reviewed_at_2", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("review_comment_2", sa.String(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("proposal_intake", schema=None) as batch_op:
        batch_op.drop_column("review_comment_2")
        batch_op.drop_column("reviewed_at_2")
        batch_op.drop_column("reviewer_id_2")
