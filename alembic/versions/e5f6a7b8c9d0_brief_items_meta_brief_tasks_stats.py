# -*- coding: utf-8 -*-
"""0003 brief_items add meta / brief_tasks add stats

Revision ID: e5f6a7b8c9d0
Revises: a1b2c3d4e5f6
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e5f6a7b8c9d0"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "brief_items",
        sa.Column("meta", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "brief_tasks",
        sa.Column("stats", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("brief_tasks", "stats")
    op.drop_column("brief_items", "meta")