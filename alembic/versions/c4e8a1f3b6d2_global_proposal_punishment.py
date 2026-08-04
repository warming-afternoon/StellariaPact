"""Rename and extend global proposal punishment

Revision ID: c4e8a1f3b6d2
Revises: b3d7e9f1a2c4
Create Date: 2026-08-04 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8a1f3b6d2"
down_revision: Union[str, Sequence[str], None] = "b3d7e9f1a2c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(
        "uq_global_voting_restriction_active_user",
        table_name="global_voting_restriction",
    )
    op.drop_index(
        "ix_global_voting_restriction_user_created",
        table_name="global_voting_restriction",
    )
    op.drop_index(
        "ix_global_voting_restriction_moderator_id",
        table_name="global_voting_restriction",
    )
    op.rename_table("global_voting_restriction", "global_proposal_punishment")

    with op.batch_alter_table("global_proposal_punishment") as batch_op:
        batch_op.add_column(
            sa.Column(
                "punishment_type",
                sa.String(),
                nullable=False,
                server_default="permanent_voting",
            )
        )
        batch_op.add_column(sa.Column("expires_at", sa.DateTime(), nullable=True))

    op.create_index(
        "ix_global_proposal_punishment_moderator_id",
        "global_proposal_punishment",
        ["moderator_id"],
        unique=False,
    )
    op.create_index(
        "ix_global_proposal_punishment_user_created",
        "global_proposal_punishment",
        ["target_user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_global_proposal_punishment_active_user_type",
        "global_proposal_punishment",
        ["target_user_id", "punishment_type"],
        unique=True,
        sqlite_where=sa.text("lifted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_global_proposal_punishment_active_user_type",
        table_name="global_proposal_punishment",
    )
    op.drop_index(
        "ix_global_proposal_punishment_user_created",
        table_name="global_proposal_punishment",
    )
    op.drop_index(
        "ix_global_proposal_punishment_moderator_id",
        table_name="global_proposal_punishment",
    )

    # 旧结构每名用户只能有一条未解除记录；先结束无法表示的限时处罚。
    op.execute(
        sa.text(
            "UPDATE global_proposal_punishment "
            "SET lifted_at = CURRENT_TIMESTAMP, "
            "lift_reason = '数据库降级时结束限时提案处罚' "
            "WHERE punishment_type = 'proposal_violation' AND lifted_at IS NULL"
        )
    )

    with op.batch_alter_table("global_proposal_punishment") as batch_op:
        batch_op.drop_column("expires_at")
        batch_op.drop_column("punishment_type")

    op.rename_table("global_proposal_punishment", "global_voting_restriction")
    op.create_index(
        "ix_global_voting_restriction_moderator_id",
        "global_voting_restriction",
        ["moderator_id"],
        unique=False,
    )
    op.create_index(
        "ix_global_voting_restriction_user_created",
        "global_voting_restriction",
        ["target_user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_global_voting_restriction_active_user",
        "global_voting_restriction",
        ["target_user_id"],
        unique=True,
        sqlite_where=sa.text("lifted_at IS NULL"),
    )
