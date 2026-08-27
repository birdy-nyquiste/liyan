"""Record what each run cost.

Nothing in this system has ever recorded a token, so every 知言 and 立言 run so
far cost an amount nobody can now recover. One row per Execution, written for
every terminal outcome rather than only the successful ones, is what turns the
numbers in `docs/operations/credits.md` from reasoning into measurement.

Revision ID: 20260827_0020
Revises: 20260825_0019
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op

revision = "20260827_0020"
down_revision = "20260825_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_costs",
        # Plain identifiers, not foreign keys: cleanup cascades tasks into
        # their Executions, and a cost that vanished with one would change a
        # margin retroactively.
        sa.Column("execution_id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("rate_card_version", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=True),
        sa.Column("search_calls", sa.Integer(), nullable=True),
        sa.Column("worker_milliseconds", sa.Integer(), nullable=True),
        sa.Column("stored_bytes", sa.Integer(), nullable=True),
        # Millionths of one US dollar. Nullable, because a provider that
        # reported no usage leaves a cost unknown rather than zero.
        sa.Column("cost_micros", sa.Integer(), nullable=True),
        sa.Column("charge_credits", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_execution_costs_operation_created",
        "execution_costs",
        ["operation", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_execution_costs_operation_created", table_name="execution_costs")
    op.drop_table("execution_costs")
