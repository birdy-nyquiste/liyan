"""Create formal tasks with immutable initial source history.

Revision ID: 20260822_0004
Revises: 20260822_0003
Create Date: 2026-08-22
"""

import sqlalchemy as sa
from alembic import op

revision = "20260822_0004"
down_revision = "20260822_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("next_task_number", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("tasks", sa.Column("number", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("display_name", sa.String(length=255), nullable=True))
    op.add_column(
        "tasks", sa.Column("creation_idempotency_key", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "tasks", sa.Column("creation_request_hash", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "tasks", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True)
    )
    with op.batch_alter_table("tasks") as batch:
        batch.create_unique_constraint("uq_tasks_owner_number", ["owner_id", "number"])
        batch.create_unique_constraint(
            "uq_tasks_owner_creation_idempotency_key",
            ["owner_id", "creation_idempotency_key"],
        )

    op.create_table(
        "task_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "number", name="uq_task_versions_task_number"),
    )
    op.create_index("ix_task_versions_task_id", "task_versions", ["task_id"])
    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sources_task_id", "sources", ["task_id"])
    op.create_table(
        "source_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("provenance", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_source_revisions_source_id", "source_revisions", ["source_id"])
    op.create_table(
        "task_version_sources",
        sa.Column("task_version_id", sa.Uuid(), nullable=False),
        sa.Column("source_revision_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_version_id"], ["task_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["source_revision_id"], ["source_revisions.id"]),
        sa.PrimaryKeyConstraint("task_version_id", "source_revision_id"),
    )
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("current_version_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_tasks_current_version_id",
            "task_versions",
            ["current_version_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("fk_tasks_current_version_id", type_="foreignkey")
        batch.drop_column("current_version_id")
    op.drop_table("task_version_sources")
    op.drop_index("ix_source_revisions_source_id", table_name="source_revisions")
    op.drop_table("source_revisions")
    op.drop_index("ix_sources_task_id", table_name="sources")
    op.drop_table("sources")
    op.drop_index("ix_task_versions_task_id", table_name="task_versions")
    op.drop_table("task_versions")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("uq_tasks_owner_creation_idempotency_key", type_="unique")
        batch.drop_constraint("uq_tasks_owner_number", type_="unique")
        batch.drop_column("created_at")
        batch.drop_column("creation_request_hash")
        batch.drop_column("creation_idempotency_key")
        batch.drop_column("display_name")
        batch.drop_column("number")
    op.drop_column("users", "next_task_number")
