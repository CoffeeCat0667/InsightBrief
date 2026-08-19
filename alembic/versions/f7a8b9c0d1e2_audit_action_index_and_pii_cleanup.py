"""audit action index

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0

The authentication audit PII cleanup is intentionally not part of the
automatic migration chain; it requires a separate, explicit data-retention
approval.
"""
from alembic import op
import sqlalchemy as sa

revision = "f7a8b9c0d1e2"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ensure_schema() may have created this index before Alembic runs.
    op.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_audit_logs_action "
            "ON audit_logs (action)"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
