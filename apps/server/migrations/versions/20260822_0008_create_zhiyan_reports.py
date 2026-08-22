"""Create immutable 知言报告 records and free Executions from one target table.

Revision ID: 20260822_0008
Revises: 20260822_0007
Create Date: 2026-08-22
"""

import sqlalchemy as sa
from alembic import op

revision = "20260822_0008"
down_revision = "20260822_0007"
branch_labels = None
depends_on = None

ACTIVE_STATUSES = "status IN ('queued', 'running', 'cancel_requested')"


def _executions_table(*, target_foreign_key: bool) -> sa.Table:
    """The executions table as this revision leaves it, for SQLite batch copies."""
    metadata = sa.MetaData()
    constraints: list[sa.schema.SchemaItem] = [
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "target_id",
            "input_version",
            "attempt",
            name="uq_executions_target_input_attempt",
        ),
    ]
    if target_foreign_key:
        constraints.append(
            sa.ForeignKeyConstraint(
                ["target_id"], ["source_preparations.id"], ondelete="CASCADE"
            )
        )
    table = sa.Table(
        "executions",
        metadata,
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
        *constraints,
    )
    sa.Index("ix_executions_owner_id", table.c.owner_id)
    sa.Index("ix_executions_target_id", table.c.target_id)
    sa.Index(
        "uq_executions_one_active_per_target",
        table.c.target_id,
        unique=True,
        postgresql_where=sa.text(ACTIVE_STATUSES),
        sqlite_where=sa.text(ACTIVE_STATUSES),
    )
    return table


def _rebuild_executions(*, target_foreign_key: bool) -> None:
    """Executions target several kinds of business object, so target_id carries no key."""
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            "executions",
            copy_from=_executions_table(target_foreign_key=target_foreign_key),
            recreate="always",
        ):
            pass
        return
    inspector = sa.inspect(bind)
    existing = {
        key["name"]
        for key in inspector.get_foreign_keys("executions")
        if key["constrained_columns"] == ["target_id"] and key["name"]
    }
    for name in existing:
        op.drop_constraint(name, "executions", type_="foreignkey")
    if target_foreign_key:
        op.create_foreign_key(
            "fk_executions_target_id",
            "executions",
            "source_preparations",
            ["target_id"],
            ["id"],
            ondelete="CASCADE",
        )


def upgrade() -> None:
    _rebuild_executions(target_foreign_key=False)
    op.create_table(
        "zhiyan_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("source_revision_id", sa.Uuid(), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("provider_response_id", sa.String(length=128), nullable=True),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("search_actions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_revision_id"], ["source_revisions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("execution_id"),
        sa.UniqueConstraint("source_revision_id"),
    )
    op.create_index("ix_zhiyan_reports_owner_id", "zhiyan_reports", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_zhiyan_reports_owner_id", table_name="zhiyan_reports")
    op.drop_table("zhiyan_reports")
    _rebuild_executions(target_foreign_key=True)
