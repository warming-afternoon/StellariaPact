"""Add is_special to proposal

Revision ID: 4d6e8f0a1b2c
Revises: 3c5a7e9d1f2b
Create Date: 2026-05-24 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4d6e8f0a1b2c"
down_revision: Union[str, Sequence[str], None] = "3c5a7e9d1f2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("proposal", sa.Column("is_special", sa.Boolean(), nullable=False, server_default="0"))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("proposal", "is_special")
