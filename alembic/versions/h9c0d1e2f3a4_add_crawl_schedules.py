"""add persistent crawl schedules and automatic brief links

Revision ID: h9c0d1e2f3a4
Revises: g8b9c0d1e2f3
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "h9c0d1e2f3a4"
down_revision = "g8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crawl_schedules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("interval_hours", sa.Integer(), nullable=False),
        sa.Column("max_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_ids", postgresql.JSONB(), nullable=True),
        sa.Column("max_items", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("domestic_max_ratio", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("generate_brief", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_task_id", sa.Integer(), nullable=True),
        sa.Column("last_brief_task_id", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawl_schedules_user_id", "crawl_schedules", ["user_id"])
    op.create_index("ix_crawl_schedules_next_run_at", "crawl_schedules", ["next_run_at"])

    op.add_column("crawl_tasks", sa.Column("schedule_id", sa.Integer(), nullable=True))
    op.add_column(
        "crawl_tasks",
        sa.Column("generate_brief", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_foreign_key(
        "fk_crawl_tasks_schedule_id_crawl_schedules",
        "crawl_tasks",
        "crawl_schedules",
        ["schedule_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_crawl_tasks_schedule_id", "crawl_tasks", ["schedule_id"])

    op.add_column("brief_tasks", sa.Column("origin_crawl_task_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_brief_tasks_origin_crawl_task_id_crawl_tasks",
        "brief_tasks",
        "crawl_tasks",
        ["origin_crawl_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_brief_tasks_origin_crawl_task_id",
        "brief_tasks",
        ["origin_crawl_task_id"],
    )

    op.create_table(
        "crawl_task_articles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("crawl_task_id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["crawl_task_id"], ["crawl_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("crawl_task_id", "article_id", name="uq_crawl_task_articles_task_article"),
    )
    op.create_index("ix_crawl_task_articles_crawl_task_id", "crawl_task_articles", ["crawl_task_id"])
    op.create_index("ix_crawl_task_articles_article_id", "crawl_task_articles", ["article_id"])


def downgrade() -> None:
    op.drop_index("ix_crawl_task_articles_article_id", table_name="crawl_task_articles")
    op.drop_index("ix_crawl_task_articles_crawl_task_id", table_name="crawl_task_articles")
    op.drop_table("crawl_task_articles")
    op.drop_constraint("uq_brief_tasks_origin_crawl_task_id", "brief_tasks", type_="unique")
    op.drop_constraint("fk_brief_tasks_origin_crawl_task_id_crawl_tasks", "brief_tasks", type_="foreignkey")
    op.drop_column("brief_tasks", "origin_crawl_task_id")
    op.drop_index("ix_crawl_tasks_schedule_id", table_name="crawl_tasks")
    op.drop_constraint("fk_crawl_tasks_schedule_id_crawl_schedules", "crawl_tasks", type_="foreignkey")
    op.drop_column("crawl_tasks", "generate_brief")
    op.drop_column("crawl_tasks", "schedule_id")
    op.drop_index("ix_crawl_schedules_next_run_at", table_name="crawl_schedules")
    op.drop_index("ix_crawl_schedules_user_id", table_name="crawl_schedules")
    op.drop_table("crawl_schedules")
