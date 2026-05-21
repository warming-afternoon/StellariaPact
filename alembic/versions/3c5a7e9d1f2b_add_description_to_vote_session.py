"""Add description to vote_session

Revision ID: 3c5a7e9d1f2b
Revises: 2b7e8d9f0c1a
Create Date: 2026-05-21 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3c5a7e9d1f2b"
down_revision: Union[str, Sequence[str], None] = "2b7e8d9f0c1a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("vote_session", sa.Column("description", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("vote_session", "description")
