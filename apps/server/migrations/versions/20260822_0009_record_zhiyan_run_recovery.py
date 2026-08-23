"""Record why a run exists, when its target may run again, and what arrived late.

Bounded recovery needs three facts an Execution did not yet hold: whether a run
is the initial operation, its one automatic retry, or a user's manual retry; the
server-authoritative moment the target may next start; and the provider output
that arrived after cancellation or after another run's report was already
accepted, which is kept for tracing and never becomes business content. Existing
Executions were all user-initiated work, so they backfill as the initial run.

Revision ID: 20260822_0009
Revises: 20260822_0008
Create Date: 2026-08-22
"""

import sqlalchemy as sa
from alembic import op

revision = "20260822_0009"
down_revision = "20260822_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("executions") as batch:
        batch.add_column(
            sa.Column(
                "origin",
                sa.String(length=16),
                nullable=False,
                server_default="initial",
            )
        )
        batch.add_column(
            sa.Column("retry_allowed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("stale_result", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("executions") as batch:
        batch.drop_column("stale_result")
        batch.drop_column("retry_allowed_at")
        batch.drop_column("origin")
