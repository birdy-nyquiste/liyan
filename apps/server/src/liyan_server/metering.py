"""Writing down what one run cost, while the only copy is still in memory.

`usage` exists for the length of a provider call and nowhere else: it is not on
the Execution, not in the report, and not recoverable afterwards. So unlike
every other operational fact in this system, a cost cannot be reconciled by a
later sweep — if the run ends without recording it, that run's cost is gone.

That is why this is called from the transaction that ends a run rather than
alongside it, and why it never raises. A 知言报告 must not be lost because a
measurement failed; the cost of that choice is a row with nothing on it, which
is countable, and the cost of the alternative is real work thrown away.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from liyan_server.database import Execution, ExecutionCost, aware_utc
from liyan_server.provider_usage import ProviderUsage
from liyan_server.rate_card import (
    CAPTURE_CREDITS,
    RATE_CARD_VERSION,
    credits_for,
    provider_cost_micros,
    storage_cost_micros,
    worker_cost_micros,
)

logger = logging.getLogger(__name__)

#: Operations whose cost is dominated by a provider call rather than by the
#: worker that made it. For these, a missing `usage` leaves the cost unknown —
#: everything else has no provider term to be missing, and its worker time and
#: bytes really are the whole of what it cost.
TOKEN_METERED_OPERATIONS = frozenset({"analyze_source", "generate_article"})

#: Operations charged a flat fee per 来源 rather than from what they measured.
#: A 250x difference in a 来源's length makes only a few times' difference in
#: what capturing it costs, so the fee is a floor covering the largest file this
#: system accepts. The measured cost beside it is how anyone finds out whether
#: that is still the right number.
FLAT_CHARGED_OPERATIONS = frozenset({"fetch_url", "parse_file"})


def _held_milliseconds(execution: Execution, now: datetime) -> int | None:
    """How long this run held a worker.

    Measured from when it started rather than when it was queued: waiting in the
    queue costs nothing, and counting it would charge users more the busier the
    system was.
    """
    if execution.started_at is None:
        return None
    finished = aware_utc(execution.finished_at) if execution.finished_at else now
    return max(0, int((finished - aware_utc(execution.started_at)).total_seconds() * 1000))


def _charge(operation: str, cost_micros: int | None, chargeable: bool) -> int | None:
    """What this run would be charged, which is not always what it cost.

    Capture is a flat fee and is known before it runs, so its charge does not
    follow its measurement — which is the point of recording both.
    """
    if operation in FLAT_CHARGED_OPERATIONS:
        return CAPTURE_CREDITS if chargeable else 0
    if cost_micros is None:
        return None
    return credits_for(cost_micros) if chargeable else 0


def record_execution_cost(
    session: Session,
    execution: Execution,
    *,
    chargeable: bool,
    usage: ProviderUsage | None = None,
    model: str | None = None,
    search_calls: int | None = None,
    stored_bytes: int | None = None,
    now: datetime | None = None,
) -> None:
    """Record what this run consumed, inside the transaction that ends it.

    `chargeable` says whether the run produced something a user could be asked
    to pay for. A cost is recorded either way — the provider invoiced 立言阁 for
    a report nobody kept exactly as it did for one that was accepted — and the
    difference between the two is how much failure this product absorbs.

    Nothing is charged yet. `charge_credits` is what *would* be, so that the
    numbers in `credits.md` can be checked before anybody's balance depends on
    them.
    """
    moment = now or datetime.now(UTC)
    try:
        if session.get(ExecutionCost, execution.id) is not None:
            return

        held = _held_milliseconds(execution, moment)
        provider_micros = (
            provider_cost_micros(usage, model) if usage is not None and model else None
        )
        # A token-metered run whose provider term is missing has an unknown
        # cost, not a partial one. Reporting its worker time alone would
        # understate it by two orders of magnitude while looking like a real
        # number — which is worse than a null anybody can count.
        cost_micros: int | None = None
        if provider_micros is not None or execution.operation not in TOKEN_METERED_OPERATIONS:
            cost_micros = provider_micros or 0
            cost_micros += worker_cost_micros(held) if held is not None else 0
            cost_micros += storage_cost_micros(stored_bytes) if stored_bytes else 0

        session.add(
            ExecutionCost(
                execution_id=execution.id,
                owner_id=execution.owner_id,
                operation=execution.operation,
                model=model,
                rate_card_version=RATE_CARD_VERSION,
                input_tokens=usage.input_tokens if usage else None,
                cached_input_tokens=usage.cached_input_tokens if usage else None,
                output_tokens=usage.output_tokens if usage else None,
                reasoning_tokens=usage.reasoning_tokens if usage else None,
                search_calls=search_calls,
                worker_milliseconds=held,
                stored_bytes=stored_bytes,
                cost_micros=cost_micros,
                charge_credits=_charge(execution.operation, cost_micros, chargeable),
                created_at=moment,
            )
        )
    except Exception:
        # Diagnostic, like a heartbeat. A run that produced business content
        # must never lose it because its cost could not be written down.
        logger.warning(
            "execution_cost_not_recorded",
            extra={"execution_id": str(execution.id), "operation": execution.operation},
        )
