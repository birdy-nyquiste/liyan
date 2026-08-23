"""Create durable 立言 article targets and generated results.

Revision ID: 20260822_0011
Revises: 20260822_0010
Create Date: 2026-08-22
"""

import sqlalchemy as sa
from alembic import op

revision = "20260822_0011"
down_revision = "20260822_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("executions") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("request_hash", sa.String(length=64), nullable=True))
        batch.create_unique_constraint(
            "uq_executions_owner_operation_idempotency",
            ["owner_id", "operation", "idempotency_key"],
        )

    op.create_table(
        "liyan_articles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("task_version_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_version_id"], ["task_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_version_id", name="uq_liyan_articles_task_version_id"),
    )
    op.create_index("ix_liyan_articles_owner_id", "liyan_articles", ["owner_id"])

    op.create_table(
        "liyan_run_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("article_id", sa.Uuid(), nullable=False),
        sa.Column("task_version_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("provider_response_id", sa.String(length=128), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["article_id"], ["liyan_articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["task_version_id"], ["task_versions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id", name="uq_liyan_run_results_execution_id"),
    )
    op.create_index("ix_liyan_run_results_owner_id", "liyan_run_results", ["owner_id"])
    op.create_index("ix_liyan_run_results_article_id", "liyan_run_results", ["article_id"])


def downgrade() -> None:
    op.drop_index("ix_liyan_run_results_article_id", table_name="liyan_run_results")
    op.drop_index("ix_liyan_run_results_owner_id", table_name="liyan_run_results")
    op.drop_table("liyan_run_results")
    op.drop_index("ix_liyan_articles_owner_id", table_name="liyan_articles")
    op.drop_table("liyan_articles")
    with op.batch_alter_table("executions") as batch:
        batch.drop_constraint("uq_executions_owner_operation_idempotency", type_="unique")
        batch.drop_column("request_hash")
        batch.drop_column("idempotency_key")
