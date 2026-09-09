"""Add third administrator review to proposal intake."""

import sqlalchemy as sa
from alembic import op

revision = "08b1d3f5a7c9"
down_revision = "f7a9c2e4b6d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("proposal_intake") as batch_op:
        batch_op.add_column(sa.Column("reviewer_id_3", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("reviewed_at_3", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("review_comment_3", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("proposal_intake") as batch_op:
        batch_op.drop_column("review_comment_3")
        batch_op.drop_column("reviewed_at_3")
        batch_op.drop_column("reviewer_id_3")
