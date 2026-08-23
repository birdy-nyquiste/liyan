"""Create independent 发布任务 records that outlive their 立言任务.

Revision ID: 20260823_0013
Revises: 20260822_0012
Create Date: 2026-08-23
"""

import sqlalchemy as sa
from alembic import op

revision = "20260823_0013"
down_revision = "20260822_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "publish_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        # The task, version, and Revision are identifiers rather than foreign
        # keys: this evidence must survive deletion of the 立言任务 it came from.
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("task_version_id", sa.Uuid(), nullable=False),
        sa.Column("revision_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("target_key", sa.String(length=64), nullable=False),
        sa.Column("target_platform", sa.String(length=64), nullable=False),
        sa.Column("target_display_name", sa.String(length=255), nullable=False),
        sa.Column("target_site_url", sa.Text(), nullable=False),
        sa.Column("target_api_base_url", sa.Text(), nullable=False),
        sa.Column("target_author", sa.String(length=255), nullable=False),
        sa.Column("post_type", sa.String(length=32), nullable=False),
        sa.Column("requested_status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body_markdown", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("preview_url", sa.Text(), nullable=True),
        sa.Column("preview_path", sa.Text(), nullable=True),
        sa.Column("external_slug", sa.String(length=255), nullable=True),
        sa.Column("external_version", sa.String(length=64), nullable=True),
        sa.Column("response_evidence", sa.JSON(), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_publish_tasks_owner_idempotency_key",
        ),
    )
    op.create_index("ix_publish_tasks_owner_id", "publish_tasks", ["owner_id"])
    op.create_index("ix_publish_tasks_revision_id", "publish_tasks", ["revision_id"])


def downgrade() -> None:
    op.drop_index("ix_publish_tasks_revision_id", table_name="publish_tasks")
    op.drop_index("ix_publish_tasks_owner_id", table_name="publish_tasks")
    op.drop_table("publish_tasks")
