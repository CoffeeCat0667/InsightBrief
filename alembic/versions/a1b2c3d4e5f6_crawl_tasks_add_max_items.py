"""crawl_tasks add max_items

Revision ID: a1b2c3d4e5f6
Revises: bd1d9d7a28fa
Create Date: 2026-08-16 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'bd1d9d7a28fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'crawl_tasks',
        sa.Column('max_items', sa.Integer(), nullable=False, server_default='30'),
    )


def downgrade() -> None:
    op.drop_column('crawl_tasks', 'max_items')