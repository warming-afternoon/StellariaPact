"""新增提案累计处罚、解除审计及原帖公示位置。

Revision ID: a8b0d2e4f6c1
Revises: 08b1d3f5a7c9
"""

import sqlalchemy as sa
from alembic import op

revision = "a8b0d2e4f6c1"
down_revision = "08b1d3f5a7c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """增加累计及解除字段，并按既有记录的处罚结果回填计数标记。"""
    if "punishment_record" not in sa.inspect(op.get_bind()).get_table_names():
        return
    with op.batch_alter_table("punishment_record") as batch_op:
        batch_op.add_column(
            sa.Column(
                "counts_toward_cumulative", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
        batch_op.add_column(sa.Column("lifted_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("lifted_by_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("lift_reason", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("source_publicity_message_id", sa.Integer(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE punishment_record SET counts_toward_cumulative = 1 "
            "WHERE reason != :off_topic AND (voting_allowed = 0 OR mute_end_time IS NOT NULL)"
        ).bindparams(off_topic="请不要歪楼滑坡")
    )


def downgrade() -> None:
    """移除新增字段，保留原处罚记录及正式公示位置。"""
    if "punishment_record" not in sa.inspect(op.get_bind()).get_table_names():
        return
    with op.batch_alter_table("punishment_record") as batch_op:
        for column in (
            "source_publicity_message_id",
            "lift_reason",
            "lifted_by_id",
            "lifted_at",
            "counts_toward_cumulative",
        ):
            batch_op.drop_column(column)
