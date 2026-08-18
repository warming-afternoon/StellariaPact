"""新增模板发言模式和消息元数据

Revision ID: e6b8c1d4f2a0
Revises: d5a7c9e1f3b6
Create Date: 2026-08-18 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e6b8c1d4f2a0"
down_revision: Union[str, Sequence[str], None] = "d5a7c9e1f3b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建模板发言模式表、消息元数据表及其索引。"""
    op.create_table(
        "structured_speech_mode",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("forum_id", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("previous_slowmode_delay", sa.Integer(), nullable=False),
        sa.Column("enabled_by_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_structured_speech_mode_thread",
        "structured_speech_mode",
        ["thread_id"],
        unique=True,
    )
    op.create_index(
        "ix_structured_speech_mode_status",
        "structured_speech_mode",
        ["status"],
        unique=False,
    )

    op.create_table(
        "structured_speech_message",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("webhook_id", sa.Integer(), nullable=False),
        sa.Column("guild_id", sa.Integer(), nullable=False),
        sa.Column("thread_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_structured_speech_message_webhook",
        "structured_speech_message",
        ["webhook_id"],
        unique=False,
    )
    op.create_index(
        "uq_structured_speech_message_discord",
        "structured_speech_message",
        ["message_id"],
        unique=True,
    )
    op.create_index(
        "ix_structured_speech_message_thread_user_created",
        "structured_speech_message",
        ["thread_id", "user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """删除模板发言消息元数据表和模式表。"""
    op.drop_index(
        "ix_structured_speech_message_thread_user_created",
        table_name="structured_speech_message",
    )
    op.drop_index(
        "ix_structured_speech_message_webhook",
        table_name="structured_speech_message",
    )
    op.drop_index(
        "uq_structured_speech_message_discord",
        table_name="structured_speech_message",
    )
    op.drop_table("structured_speech_message")
    op.drop_index("ix_structured_speech_mode_status", table_name="structured_speech_mode")
    op.drop_index("uq_structured_speech_mode_thread", table_name="structured_speech_mode")
    op.drop_table("structured_speech_mode")
