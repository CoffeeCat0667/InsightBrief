"""add existed_count to crawl_runs

Revision ID: i1a2b3c4d5e6
Revises: h9c0d1e2f3a4
"""
from alembic import op
import sqlalchemy as sa

revision = "i1a2b3c4d5e6"
down_revision = "h9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crawl_runs",
        sa.Column("existed_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("crawl_runs", "existed_count")
