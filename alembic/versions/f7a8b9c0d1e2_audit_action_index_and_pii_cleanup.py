"""audit action index and remove authentication PII from details

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
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
    # Authentication audit details historically contained username/email. Keep
    # the event and reason, but remove those PII keys in place.
    op.execute(
        sa.text(
            """
            UPDATE audit_logs
            SET detail = detail - 'username' - 'email'
            WHERE action IN (
                'user.register', 'user.register_failed',
                'user.login', 'user.login_failed'
            )
              AND detail IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
