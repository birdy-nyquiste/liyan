"""How many times one 知言 生成 target may run, and when it may run again.

Function Spec §5.3–5.4 bounds the whole orchestration: the initial operation gets
at most two AgentRuns, the second created automatically and only when the first
failed for a reason another run could survive. Every later run is a user's manual
retry, at most two in any rolling 30 minutes, and the server — never the client —
decides the moment the next one becomes allowed.

This module is the whole policy and holds no database or transport dependency, so
the rule stays one readable place instead of being spread across API and worker.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from liyan_server.execution_states import RunOrigin

#: The initial operation's bounded recovery: the first run plus one automatic retry.
INITIAL_ATTEMPT_LIMIT = 2

#: How many manual retries one generation target may start inside the window.
MANUAL_RETRY_LIMIT = 2

MANUAL_RETRY_WINDOW = timedelta(minutes=30)

#: A failure another identical run could plausibly survive. Anything absent from
#: this set never spends the automatic attempt: a missing API key, an Execution
#: whose approved input is gone, or an unreachable queue all fail again the same way.
RECOVERABLE_FAILURE_CODES: frozenset[str] = frozenset(
    {
        "provider_unavailable",
        "provider_rate_limited",
        "provider_refused",
        "incomplete_provider_response",
        "invalid_provider_response",
        "invalid_report_schema",
        "invalid_report_identifier",
        "invalid_report_reference",
        "missing_empty_state",
        "unsupported_fact_verdict",
        "unsupported_evidence_url",
        "unopened_evidence",
        "unused_evidence",
    }
)

_PROVIDER_BACKOFF = timedelta(seconds=30)
_RATE_LIMITED_BACKOFF = timedelta(seconds=60)
_REJECTED_REPORT_BACKOFF = timedelta(seconds=15)

_REJECTED_REPORT_CODES: frozenset[str] = frozenset(
    {
        "invalid_report_schema",
        "invalid_report_identifier",
        "invalid_report_reference",
        "missing_empty_state",
        "unsupported_fact_verdict",
        "unsupported_evidence_url",
        "unopened_evidence",
        "unused_evidence",
    }
)


@dataclass(frozen=True)
class RetryState:
    """What the server permits next, in the only terms a client may act on."""

    allowed: bool
    remaining: int
    allowed_at: datetime | None


def is_recoverable(failure_code: str | None) -> bool:
    return failure_code in RECOVERABLE_FAILURE_CODES


def automatic_attempt_permitted(*, origin: RunOrigin, attempt: int, failure_code: str) -> bool:
    """Only the initial operation recovers on its own, and only once."""
    return origin == "initial" and attempt < INITIAL_ATTEMPT_LIMIT and is_recoverable(failure_code)


def retry_allowed_at(finished_at: datetime, failure_code: str) -> datetime:
    """The earliest moment a new run for this target may start after one failure."""
    if failure_code == "provider_rate_limited":
        return finished_at + _RATE_LIMITED_BACKOFF
    if failure_code in _REJECTED_REPORT_CODES:
        return finished_at + _REJECTED_REPORT_BACKOFF
    if is_recoverable(failure_code):
        return finished_at + _PROVIDER_BACKOFF
    return finished_at


def retry_state(
    *,
    now: datetime,
    manual_run_times: Sequence[datetime],
    earliest_retry_at: datetime | None,
) -> RetryState:
    """Combine the failure's own backoff with the rolling manual-retry allowance.

    `manual_run_times` is when each manual retry for this target was created,
    whatever became of it: cancelling a run does not refund the call it made.
    """
    inside_window = [moment for moment in manual_run_times if moment > now - MANUAL_RETRY_WINDOW]
    remaining = max(0, MANUAL_RETRY_LIMIT - len(inside_window))
    allowed_at = earliest_retry_at
    if remaining == 0:
        window_release = min(inside_window) + MANUAL_RETRY_WINDOW
        allowed_at = max(allowed_at, window_release) if allowed_at else window_release
    if allowed_at is not None and allowed_at <= now:
        allowed_at = None
    return RetryState(
        allowed=remaining > 0 and allowed_at is None,
        remaining=remaining,
        allowed_at=allowed_at,
    )
