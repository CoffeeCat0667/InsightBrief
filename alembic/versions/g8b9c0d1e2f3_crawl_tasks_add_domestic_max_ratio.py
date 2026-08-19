"""crawl_tasks add domestic max ratio

Revision ID: g8b9c0d1e2f3
Revises: f7a8b9c0d1e2
"""
from alembic import op
import sqlalchemy as sa

revision = "g8b9c0d1e2f3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "crawl_tasks",
        sa.Column(
            "domestic_max_ratio",
            sa.Integer(),
            nullable=False,
            server_default="100",
        ),
    )


def downgrade() -> None:
    op.drop_column("crawl_tasks", "domestic_max_ratio")
