"""Add global voting restriction

Revision ID: 8e1a2b3c4d5f
Revises: 7c9d2e4f6a8b
Create Date: 2026-07-15 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "8e1a2b3c4d5f"
down_revision: Union[str, Sequence[str], None] = "7c9d2e4f6a8b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "global_voting_restriction" in inspector.get_table_names():
        return

    op.create_table(
        "global_voting_restriction",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=False),
        sa.Column("moderator_id", sa.Integer(), nullable=False),
        sa.Column("origin_guild_id", sa.Integer(), nullable=False),
        sa.Column("origin_channel_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("evidence_url", sa.String(), nullable=True),
        sa.Column("evidence_filename", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("lifted_by_id", sa.Integer(), nullable=True),
        sa.Column("lift_reason", sa.String(), nullable=True),
        sa.Column("lifted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
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


def downgrade() -> None:
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
    op.drop_table("global_voting_restriction")
