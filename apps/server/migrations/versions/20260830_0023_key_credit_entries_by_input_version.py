"""Put `input_version` in the key that says which run a 预扣 belongs to.

`uq_credit_entries_run` was `(kind, target_type, target_id, attempt)`, described
in the model as mirroring the triple `Execution` uses. It does not: an Execution
is unique on `(target_id, input_version, attempt)`, and the ledger dropped the
middle one.

That is invisible for every operation but one. 知言 and capture only ever run at
version 1, so the attempt alone identifies them. 立言 does not: regenerating an
article after a *success* is not a retry, so it takes the next `input_version`
and restarts `attempt` at 1. Two generations of one article therefore arrived at
this index as the same row. The second one's 预扣 collided, `hold` found the
first and returned None, and the run went ahead — unbilled, and with nothing in
使用记录 to say it had happened. `settle` then collided the same way. Staging has
one article with three successful generations, 55 额度 of metered cost, and 24
额度 actually taken.

Everything already written is version 1. Every non-立言 run is version 1 by
construction, and the only 立言 预扣 that exist are first generations — the later
ones are precisely what this bug discarded — so the backfill is exact rather
than a best guess. It is checked rather than assumed: a row that cannot be
matched to a version-1 run stops the migration instead of being quietly
numbered.

Nothing is repaid here. The 额度 those dropped runs should have cost are not
recoverable from what was kept — the holds were never written — and inventing
them from `execution_costs` would put a charge in the ledger that no 预扣 ever
backed. The undercharge stays where it happened.

Revision ID: 20260830_0023
Revises: 20260829_0022
Create Date: 2026-08-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "20260830_0023"
down_revision = "20260829_0022"
branch_labels = None
depends_on = None

#: 预扣 and 结算 are the only kinds the run index covers, and the only ones with
#: a run to belong to. 赠送, 购买, and 额度退回 keep a null here, as they already
#: do for `target_id` and `attempt`.
_RUN_KINDS = "kind IN ('hold', 'settle')"


def upgrade() -> None:
    op.add_column("credit_entries", sa.Column("input_version", sa.Integer(), nullable=True))

    unmatched = (
        op.get_bind()
        .execute(
            text(
                f"""
                SELECT count(*) FROM credit_entries c
                WHERE {_RUN_KINDS}
                  AND NOT EXISTS (
                    SELECT 1 FROM executions e
                     WHERE e.target_type = c.target_type
                       AND e.target_id = c.target_id
                       AND e.attempt = c.attempt
                       AND e.input_version = 1
                  )
                """
            )
        )
        .scalar_one()
    )
    if unmatched:
        raise RuntimeError(
            f"{unmatched} 预扣/结算 rows do not belong to a version-1 run; "
            "backfilling them as version 1 would attach 额度 to the wrong run."
        )

    op.execute(text(f"UPDATE credit_entries SET input_version = 1 WHERE {_RUN_KINDS}"))

    op.drop_index("uq_credit_entries_run", table_name="credit_entries")
    op.create_index(
        "uq_credit_entries_run",
        "credit_entries",
        ["kind", "target_type", "target_id", "input_version", "attempt"],
        unique=True,
        postgresql_where=text(_RUN_KINDS),
        sqlite_where=text(_RUN_KINDS),
    )


def downgrade() -> None:
    # Going back re-imposes one 预扣 per (target, attempt), so an article with
    # more than one generation would now collide. Nothing is deleted to make
    # room: the index simply fails to build, which is the honest outcome —
    # discarding a 预扣 to fit an older key is how this went wrong the first
    # time.
    op.drop_index("uq_credit_entries_run", table_name="credit_entries")
    op.create_index(
        "uq_credit_entries_run",
        "credit_entries",
        ["kind", "target_type", "target_id", "attempt"],
        unique=True,
        postgresql_where=text(_RUN_KINDS),
        sqlite_where=text(_RUN_KINDS),
    )
    op.drop_column("credit_entries", "input_version")
