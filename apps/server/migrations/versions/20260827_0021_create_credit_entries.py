"""Give 额度 a record to be read from.

Append-only, because a balance is money and a cached total is a second source of
truth for it. Nothing stores the balance: it is the sum of these rows.

Revision ID: 20260827_0021
Revises: 20260827_0020
Create Date: 2026-08-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "20260827_0021"
down_revision = "20260827_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "credit_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        # Signed: negative takes 额度, positive gives them back or adds them.
        sa.Column("amount", sa.Integer(), nullable=False),
        # Plain identifiers, mirroring Execution's triple. Not foreign keys:
        # cleanup cascades tasks into Executions, and 额度 that vanished with one
        # would change a balance retroactively.
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("execution_id", sa.Uuid(), nullable=True),
        sa.Column("stripe_event_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    # One 预扣 and one 结算 per attempt, so a settlement written both eagerly and
    # by the reconciling sweep cannot count twice.
    op.create_index(
        "uq_credit_entries_run",
        "credit_entries",
        ["kind", "target_type", "target_id", "attempt"],
        unique=True,
        postgresql_where=text("kind IN ('hold', 'settle')"),
        sqlite_where=text("kind IN ('hold', 'settle')"),
    )
    # One capture charge per 来源, however many times intake is replayed.
    op.create_index(
        "uq_credit_entries_capture",
        "credit_entries",
        ["target_type", "target_id"],
        unique=True,
        postgresql_where=text("kind = 'capture'"),
        sqlite_where=text("kind = 'capture'"),
    )
    # A redelivered Stripe event collides here rather than crediting twice.
    op.create_index(
        "uq_credit_entries_stripe_event",
        "credit_entries",
        ["stripe_event_id"],
        unique=True,
        postgresql_where=text("stripe_event_id IS NOT NULL"),
        sqlite_where=text("stripe_event_id IS NOT NULL"),
    )
    op.create_index(
        "ix_credit_entries_owner_created",
        "credit_entries",
        ["owner_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_credit_entries_owner_created", table_name="credit_entries")
    op.drop_index("uq_credit_entries_stripe_event", table_name="credit_entries")
    op.drop_index("uq_credit_entries_capture", table_name="credit_entries")
    op.drop_index("uq_credit_entries_run", table_name="credit_entries")
    op.drop_table("credit_entries")
