"""Retry policy for one 立言 generation target."""

from datetime import datetime, timedelta

from liyan_server.execution_states import RunOrigin
from liyan_server.zhiyan.recovery import (
    INITIAL_ATTEMPT_LIMIT,
    MANUAL_RETRY_LIMIT,
    MANUAL_RETRY_WINDOW,
    RetryState,
    retry_state,
)

RECOVERABLE_FAILURE_CODES: frozenset[str] = frozenset(
    {
        "provider_unavailable",
        "provider_rate_limited",
        "provider_refused",
        "incomplete_provider_response",
        "invalid_provider_response",
        "invalid_article_schema",
        "unsupported_article_markdown",
        "internal_article_reference",
        "article_generation_narration",
    }
)

_REJECTED_ARTICLE_CODES = frozenset(
    {
        "invalid_article_schema",
        "unsupported_article_markdown",
        "internal_article_reference",
        "article_generation_narration",
    }
)


def automatic_attempt_permitted(
    *, origin: RunOrigin, attempt: int, failure_code: str
) -> bool:
    return (
        origin == "initial"
        and attempt < INITIAL_ATTEMPT_LIMIT
        and failure_code in RECOVERABLE_FAILURE_CODES
    )


def retry_allowed_at(finished_at: datetime, failure_code: str) -> datetime:
    if failure_code == "provider_rate_limited":
        return finished_at + timedelta(seconds=60)
    if failure_code in _REJECTED_ARTICLE_CODES:
        return finished_at + timedelta(seconds=15)
    if failure_code in RECOVERABLE_FAILURE_CODES:
        return finished_at + timedelta(seconds=30)
    return finished_at


__all__ = [
    "MANUAL_RETRY_LIMIT",
    "MANUAL_RETRY_WINDOW",
    "RetryState",
    "automatic_attempt_permitted",
    "retry_allowed_at",
    "retry_state",
]
