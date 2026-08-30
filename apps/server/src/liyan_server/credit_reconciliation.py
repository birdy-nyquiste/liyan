"""Settling 预扣 that nothing else settled.

A 结算 is written where the number is known — inside the transaction that ends a
run, beside the cost row. That covers every terminal branch of both workers, and
it will still miss some, because two things end a run without the worker ever
reaching that code:

- The stalled sweep, which gives up on a run it presumes lost.
- Queueing itself failing after the 预扣 was taken. `queue_initial_runs` runs
  after the task transaction commits and swallows its own trouble on purpose,
  so a 任务版本 can exist holding 额度 for a run that was never dispatched.

Both leave a user's 额度 taken for work that will never happen, silently: no
error, no failed run, just a smaller number than they expected. That is the
quiet failure `limits.md` is written against, and it is why this is reconciled
rather than remembered — a terminal path nobody wires up leaks nothing.

Idempotent by the same index the eager path relies on, so both running is the
ordinary case rather than a race.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from liyan_server.credits import settle
from liyan_server.database import CreditEntry, Database, Execution, ExecutionCost, aware_utc
from liyan_server.execution_states import TERMINAL_EXECUTION_STATUSES

logger = logging.getLogger(__name__)

#: How long a 预扣 with no Execution at all may stand before it is given back.
#: Long enough that a dispatch in flight is never mistaken for one that failed,
#: which costs a user a few minutes of a number being lower than it will be.
ORPHANED_HOLD_GRACE = timedelta(minutes=30)


def _unsettled(session: Session) -> list[CreditEntry]:
    """预扣 with no 结算 of their own.

    Matched on the whole run key, not on the target. One 立言文章 can carry a
    hold per generation, so a target that has settled once is not a target that
    has settled — reading it that way would leave every later generation's 预扣
    standing forever, which is a user's 额度 taken for work that finished.
    """
    settled = select(
        CreditEntry.target_type,
        CreditEntry.target_id,
        CreditEntry.input_version,
        CreditEntry.attempt,
    ).where(CreditEntry.kind == "settle")
    return list(
        session.scalars(
            select(CreditEntry).where(
                CreditEntry.kind == "hold",
                tuple_(
                    CreditEntry.target_type,
                    CreditEntry.target_id,
                    CreditEntry.input_version,
                    CreditEntry.attempt,
                ).not_in(settled),
            )
        )
    )


def _execution_for(session: Session, held: CreditEntry) -> Execution | None:
    return session.scalar(
        select(Execution).where(
            Execution.target_type == held.target_type,
            Execution.target_id == held.target_id,
            Execution.input_version == held.input_version,
            Execution.attempt == held.attempt,
        )
    )


def reconcile_settlements(database_url: str, *, now: datetime | None = None) -> int:
    """Settle every 预扣 whose work has ended and which nobody settled.

    Returns how many it wrote, so a run that finds something to do is visible in
    the logs rather than only in a balance.
    """
    moment = now or datetime.now(UTC)
    database = Database(database_url)
    if database.engine is None:
        return 0
    written = 0
    try:
        with Session(database.engine) as session:
            for held in _unsettled(session):
                if (
                    held.target_type is None
                    or held.target_id is None
                    or held.input_version is None
                    or held.attempt is None
                ):
                    continue
                execution = _execution_for(session, held)
                if execution is None:
                    # Nothing was ever queued for it. Give it all back, once
                    # enough time has passed that a dispatch cannot still be on
                    # its way.
                    if moment - aware_utc(held.created_at) < ORPHANED_HOLD_GRACE:
                        continue
                    actual: int | None = 0
                elif execution.status in TERMINAL_EXECUTION_STATUSES:
                    # A run that did not succeed is free, whatever it cost and
                    # whatever was recorded about it. Reading a stored charge
                    # here would trust a row that may have been written by an
                    # older worker — and one written as unknown would be settled
                    # as "the 预扣 stands", which is a user paying for nothing.
                    cost = session.get(ExecutionCost, execution.id)
                    actual = (
                        0
                        if execution.status != "succeeded" or cost is None
                        else cost.charge_credits
                    )
                else:
                    continue
                entry = settle(
                    session,
                    held.owner_id,
                    target_type=held.target_type,
                    target_id=held.target_id,
                    input_version=held.input_version,
                    attempt=held.attempt,
                    actual=actual,
                    execution_id=execution.id if execution else None,
                    now=moment,
                )
                if entry is not None:
                    written += 1
            session.commit()
    except Exception:
        logger.exception("credit_reconciliation_failed")
        return 0
    finally:
        database.dispose()
    if written:
        logger.info("credits_reconciled", extra={"settlements": written})
    return written
