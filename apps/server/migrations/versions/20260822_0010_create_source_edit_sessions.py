"""Create unrecoverable source edit sessions.

Revision ID: 20260822_0010
Revises: 20260822_0009
Create Date: 2026-08-22
"""

import sqlalchemy as sa
from alembic import op

revision = "20260822_0010"
down_revision = "20260822_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("source_revisions") as batch:
        batch.add_column(sa.Column("source_preparation_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_source_revisions_source_preparation_id",
            "source_preparations",
            ["source_preparation_id"],
            ["id"],
        )
    op.create_table(
        "source_edit_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("base_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("save_idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("save_request_hash", sa.String(length=64), nullable=True),
        sa.Column("saved_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["base_version_id"], ["task_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["saved_version_id"], ["task_versions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_source_edit_sessions_owner_id", "source_edit_sessions", ["owner_id"]
    )
    op.create_index(
        "ix_source_edit_sessions_task_id", "source_edit_sessions", ["task_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_source_edit_sessions_task_id", table_name="source_edit_sessions")
    op.drop_index("ix_source_edit_sessions_owner_id", table_name="source_edit_sessions")
    op.drop_table("source_edit_sessions")
    with op.batch_alter_table("source_revisions") as batch:
        batch.drop_constraint(
            "fk_source_revisions_source_preparation_id", type_="foreignkey"
        )
        batch.drop_column("source_preparation_id")
