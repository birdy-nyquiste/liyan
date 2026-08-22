"""Create URL source preparations and durable fetch Executions.

Revision ID: 20260822_0005
Revises: 20260822_0004
Create Date: 2026-08-22
"""

import sqlalchemy as sa
from alembic import op

revision = "20260822_0005"
down_revision = "20260822_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_preparations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("client_session_id", sa.String(length=255), nullable=False),
        sa.Column("client_source_id", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("input_url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("input_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("provenance", sa.Text(), nullable=True),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("active_execution_id", sa.Uuid(), nullable=True),
        sa.Column("accepted_result_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "client_session_id",
            "client_source_id",
            name="uq_source_preparations_owner_client_identity",
        ),
    )
    op.create_index("ix_source_preparations_owner_id", "source_preparations", ["owner_id"])
    op.create_table(
        "executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("input_version", sa.Integer(), nullable=False),
        sa.Column("input_identity", sa.String(length=64), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("trace_id", sa.Uuid(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("internal_error", sa.Text(), nullable=True),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["source_preparations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "target_id",
            "input_version",
            "attempt",
            name="uq_executions_target_input_attempt",
        ),
    )
    op.create_index("ix_executions_owner_id", "executions", ["owner_id"])
    op.create_index("ix_executions_target_id", "executions", ["target_id"])
    op.create_index(
        "uq_executions_one_active_per_target",
        "executions",
        ["target_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running', 'cancel_requested')"),
        sqlite_where=sa.text("status IN ('queued', 'running', 'cancel_requested')"),
    )
    op.create_table(
        "url_fetch_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("input_identity", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("provenance", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id"),
    )
    with op.batch_alter_table("executions") as batch:
        batch.create_foreign_key(
            "fk_executions_result_id",
            "url_fetch_results",
            ["result_id"],
            ["id"],
        )
    with op.batch_alter_table("source_preparations") as batch:
        batch.create_foreign_key(
            "fk_source_preparations_active_execution_id",
            "executions",
            ["active_execution_id"],
            ["id"],
        )
        batch.create_foreign_key(
            "fk_source_preparations_accepted_result_id",
            "url_fetch_results",
            ["accepted_result_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("source_preparations") as batch:
        batch.drop_constraint("fk_source_preparations_accepted_result_id", type_="foreignkey")
        batch.drop_constraint("fk_source_preparations_active_execution_id", type_="foreignkey")
    with op.batch_alter_table("executions") as batch:
        batch.drop_constraint("fk_executions_result_id", type_="foreignkey")
    op.drop_table("url_fetch_results")
    op.drop_index("ix_executions_target_id", table_name="executions")
    op.drop_index("ix_executions_owner_id", table_name="executions")
    op.drop_index("uq_executions_one_active_per_target", table_name="executions")
    op.drop_table("executions")
    op.drop_index("ix_source_preparations_owner_id", table_name="source_preparations")
    op.drop_table("source_preparations")
