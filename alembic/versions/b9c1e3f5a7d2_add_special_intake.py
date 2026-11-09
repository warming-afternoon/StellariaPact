"""为预审草案记录特殊提案标记。

Revision ID: b9c1e3f5a7d2
Revises: a8b0d2e4f6c1
"""

import sqlalchemy as sa
from alembic import op

revision = "b9c1e3f5a7d2"
down_revision = "a8b0d2e4f6c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """添加特殊提案标记，既有草案默认为普通草案。"""
    op.add_column(
        "proposal_intake",
        sa.Column("is_special", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """移除特殊提案草案标记。"""
    with op.batch_alter_table("proposal_intake") as batch_op:
        batch_op.drop_column("is_special")
