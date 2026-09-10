"""Let a capture charge be corrected by the run it paid for.

The flat capture fee is charged at intake, in the transaction that accepts a
来源, because its price is known before the work runs. That is also what makes
it the one charge that can outlive the work it paid for: a URL fetch that times
out left the user with no 来源 and three 额度 gone, while every other operation
reaches zero through a 结算 correcting its 预扣. 使用条款 3.1 has always said
otherwise — 抓取失败、未产出任何结果的来源不消耗额度 — so the ledger was the
part that disagreed.

`credits.reconcile_capture` writes the difference between what a 来源 holds and
what its last capture run says it should hold: the fee back when the run
produced nothing, the fee again when a retry finally produced something. Both
directions are needed. A one-way refund would hand back the fee on the failure
and never take it again on the retry that succeeded, which is a 来源 with
content nobody paid for.

That is what these two indexes are. `uq_credit_entries_capture` narrows to the
rows intake writes — the ones with no Execution behind them — so it still
allows exactly one intake charge per 来源, and no longer blocks the corrections.
`uq_credit_entries_capture_adjustment` allows exactly one correction per run,
which is what lets the worker that ends a run and the sweep that reconciles
what it missed both write it.

Nothing is backfilled. A refund is owed for every capture that has already
failed, but this migration cannot tell one from a 来源 that was pasted, a run
that was superseded, or an attempt still queued — that is the sweep's job,
against live Executions, and it will find them on its next pass.

Revision ID: 20260910_0025
Revises: 20260901_0024
Create Date: 2026-09-10
"""

from alembic import op
from sqlalchemy import text

revision = "20260910_0025"
down_revision = "20260901_0024"
branch_labels = None
depends_on = None

_INTAKE = "kind = 'capture' AND execution_id IS NULL"
_ADJUSTMENT = "kind IN ('capture', 'capture_refund') AND execution_id IS NOT NULL"


def upgrade() -> None:
    op.drop_index("uq_credit_entries_capture", table_name="credit_entries")
    op.create_index(
        "uq_credit_entries_capture",
        "credit_entries",
        ["target_type", "target_id"],
        unique=True,
        postgresql_where=text(_INTAKE),
        sqlite_where=text(_INTAKE),
    )
    op.create_index(
        "uq_credit_entries_capture_adjustment",
        "credit_entries",
        ["execution_id"],
        unique=True,
        postgresql_where=text(_ADJUSTMENT),
        sqlite_where=text(_ADJUSTMENT),
    )


def downgrade() -> None:
    op.drop_index("uq_credit_entries_capture_adjustment", table_name="credit_entries")
    op.drop_index("uq_credit_entries_capture", table_name="credit_entries")
    op.create_index(
        "uq_credit_entries_capture",
        "credit_entries",
        ["target_type", "target_id"],
        unique=True,
        postgresql_where=text("kind = 'capture'"),
        sqlite_where=text("kind = 'capture'"),
    )
