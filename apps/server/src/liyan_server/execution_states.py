from typing import Literal

type ExecutionStatus = Literal[
    "queued",
    "running",
    "cancel_requested",
    "cancelled",
    "failed",
    "stale",
    "succeeded",
]
type SourcePreparationStatus = Literal["processing", "ready", "warning", "failure"]

#: Why an Execution exists: the initial operation, its one automatic recovery
#: attempt, or a retry the user asked for.
type RunOrigin = Literal["initial", "automatic", "manual"]

ACTIVE_EXECUTION_STATUSES: frozenset[ExecutionStatus] = frozenset(
    {"queued", "running", "cancel_requested"}
)

_CANCELLED_MESSAGES: dict[str, str] = {
    "fetch_url": "Fetching was cancelled. Retry it or replace this source.",
    "parse_file": "Parsing was cancelled. Retry it or replace this source.",
    "analyze_source": "知言分析已取消，可重新发起。",
    "generate_article": "立言生成已取消，可重新发起。",
}

GENERIC_CANCELLED_MESSAGE = "The work was cancelled. Start it again when you are ready."


def cancelled_message(operation: str) -> str:
    """What the user reads when they cancelled one Execution.

    Cancelling is a deliberate act, so every message says the work can start
    again rather than reporting a fault. An operation with no wording of its own
    still gets an answer, because a missing phrase must not fail a cancellation.
    """
    return _CANCELLED_MESSAGES.get(operation, GENERIC_CANCELLED_MESSAGE)
