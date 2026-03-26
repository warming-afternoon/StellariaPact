"""add new features about intake and proposal

Revision ID: 1ac855605faf
Revises: 00a6cd83f4bf
Create Date: 2026-03-02 10:08:00.439157

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1ac855605faf'
down_revision: Union[str, Sequence[str], None] = '00a6cd83f4bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 检查表是否存在，如果不存在则创建
    if not op.get_bind().dialect.has_table(op.get_bind(), 'proposal_intake'):
        op.create_table('proposal_intake',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('guild_id', sa.Integer(), nullable=False),
            sa.Column('author_id', sa.Integer(), nullable=False),
            sa.Column('title', sa.String(), nullable=False),
            sa.Column('reason', sa.String(), nullable=False),
            sa.Column('motion', sa.String(), nullable=False),
            sa.Column('implementation', sa.String(), nullable=False),
            sa.Column('executor', sa.String(), nullable=False),
            sa.Column('status', sa.Integer(), nullable=False),
            sa.Column('review_thread_id', sa.Integer(), nullable=True),
            sa.Column('discussion_thread_id', sa.Integer(), nullable=True),
            sa.Column('voting_message_id', sa.Integer(), nullable=True),
            sa.Column('required_votes', sa.Integer(), nullable=False),
            sa.Column('reviewer_id', sa.Integer(), nullable=True),
            sa.Column('reviewed_at', sa.DateTime(), nullable=True),
            sa.Column('review_comment', sa.String(), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(
            op.f('ix_proposal_intake_author_id'),
            'proposal_intake',
            ['author_id'],
            unique=False,
        )
        op.create_index(
            op.f('ix_proposal_intake_guild_id'),
            'proposal_intake',
            ['guild_id'],
            unique=False,
        )
        op.create_index(
            op.f('ix_proposal_intake_status'),
            'proposal_intake',
            ['status'],
            unique=False,
        )

    # 清理旧备份表
    op.execute("DROP TABLE IF EXISTS _announcement_old_20250907")
    op.execute("DROP TABLE IF EXISTS _useractivity_old_20251012")

    # 使用 Batch 模式修改现有表 (适配 SQLite)
    with op.batch_alter_table('announcement', schema=None) as batch_op:
        batch_op.alter_column('auto_execute', type_=sa.Boolean(), existing_type=sa.Integer())

    with op.batch_alter_table('announcement_channel_monitor', schema=None) as batch_op:
        # 先删除旧索引，再创建新索引
        batch_op.drop_index('ix_announcementchannelmonitor_announcementId')
        batch_op.drop_index('ix_announcementchannelmonitor_channelId')
        batch_op.create_index(
            op.f('ix_announcement_channel_monitor_announcement_id'),
            ['announcement_id'],
            unique=False,
        )
        batch_op.create_index(
            op.f('ix_announcement_channel_monitor_channel_id'),
            ['channel_id'],
            unique=False,
        )

    with op.batch_alter_table('confirmation_session', schema=None) as batch_op:
        batch_op.drop_index('ix_confirmationsession_context')
        batch_op.drop_index('ix_confirmationsession_status')
        batch_op.drop_index('ix_confirmationsession_targetId')
        batch_op.create_index(
            op.f('ix_confirmation_session_context'),
            ['context'],
            unique=False,
        )
        batch_op.create_index(
            op.f('ix_confirmation_session_status'),
            ['status'],
            unique=False,
        )
        batch_op.create_index(
            op.f('ix_confirmation_session_target_id'),
            ['target_id'],
            unique=False,
        )

    with op.batch_alter_table('user_activity', schema=None) as batch_op:
        batch_op.alter_column('mute_end_time', type_=sa.DateTime(), existing_type=sa.DATE())
        batch_op.drop_index('ix_useractivity_contextThreadId')
        batch_op.drop_index('ix_useractivity_userId')
        batch_op.create_index(
            op.f('ix_user_activity_context_thread_id'),
            ['context_thread_id'],
            unique=False,
        )
        batch_op.create_index(
            op.f('ix_user_activity_user_id'),
            ['user_id'],
            unique=False,
        )
        batch_op.create_unique_constraint(
            'uk_user_activity_per_thread',
            ['user_id', 'context_thread_id'],
        )

    with op.batch_alter_table('user_vote', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'option_type',
                sa.Integer(),
                nullable=False,
                server_default='0',
            )
        )
        batch_op.drop_index('ix_uservote_sessionId')
        batch_op.drop_index('ix_uservote_userId')
        batch_op.create_index(
            op.f('ix_user_vote_session_id'),
            ['session_id'],
            unique=False,
        )
        batch_op.create_index(
            op.f('ix_user_vote_user_id'),
            ['user_id'],
            unique=False,
        )
        batch_op.create_unique_constraint(
            'uk_user_vote_type_option',
            ['session_id', 'user_id', 'option_type', 'choice_index'],
        )

    with op.batch_alter_table('vote_option', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'option_type',
                sa.Integer(),
                nullable=False,
                server_default='0',
            )
        )
        batch_op.add_column(sa.Column('creator_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('creator_name', sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                'data_status',
                sa.Integer(),
                nullable=False,
                server_default='1',
            )
        )
        batch_op.add_column(
            sa.Column(
                'created_at',
                sa.DateTime(),
                nullable=False,
                server_default=sa.text('(CURRENT_TIMESTAMP)'),
            )
        )
        batch_op.create_index(op.f('ix_vote_option_data_status'), ['data_status'], unique=False)
        # 先尝试删除旧约束，再创建新索引
        batch_op.drop_constraint('uk_voteoption_session_choice', type_='unique')
        batch_op.create_unique_constraint(
            'uk_vote_option_session_type_choice',
            ['session_id', 'option_type', 'choice_index'],
        )

    with op.batch_alter_table('vote_session', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'session_type',
                sa.Integer(),
                nullable=False,
                server_default='1',
            )
        )
        batch_op.add_column(sa.Column('proposal_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('intake_id', sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                'start_time',
                sa.DateTime(),
                server_default=sa.text('(CURRENT_TIMESTAMP)'),
                nullable=False,
            )
        )
        batch_op.alter_column('guild_id', nullable=False, existing_type=sa.Integer())

        # 索引重命名 (先尝试删除旧约束，再创建新索引)
        old_indexes = [
            'ix_votesession_contextMessageId',
            'ix_votesession_contextThreadId',
            'ix_votesession_status',
            'ix_votesession_votingChannelMessageId',
        ]
        for idx in old_indexes:
            try:
                batch_op.drop_index(idx)
            except Exception:
                pass

        batch_op.create_index(
            op.f('ix_vote_session_context_message_id'),
            ['context_message_id'],
            unique=False,
        )
        batch_op.create_index(
            op.f('ix_vote_session_context_thread_id'),
            ['context_thread_id'],
            unique=False,
        )
        batch_op.create_index(
            op.f('ix_vote_session_guild_id'),
            ['guild_id'],
            unique=False,
        )
        batch_op.create_index(
            op.f('ix_vote_session_session_type'),
            ['session_type'],
            unique=False,
        )
        batch_op.create_index(
            op.f('ix_vote_session_status'),
            ['status'],
            unique=False,
        )
        batch_op.create_index(
            op.f('ix_vote_session_voting_channel_message_id'),
            ['voting_channel_message_id'],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('proposal_intake')
