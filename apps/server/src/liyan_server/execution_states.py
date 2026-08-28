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

#: A 发布任务 is pending until Blog answers. `outcome_unknown` is terminal by
#: ADR-0001: transmission may have started, so 立言阁 must never resend it.
type PublishTaskStatus = Literal["pending", "succeeded", "failed", "outcome_unknown"]

#: What one movement of 额度 was. Stored literals, rendered in the workbench as
#: 赠送, 购买, 预扣 and 结算; `CONTEXT.md` defines what each one means.
#: `capture` is the flat fee a 来源 costs, which is charged outright rather than
#: held, because it is known before the work runs.
type CreditEntryKind = Literal[
    "grant",
    "purchase",
    "capture",
    "hold",
    "settle",
    "clawback",
]

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
    "publish_preview": "发布已取消。",
}

GENERIC_CANCELLED_MESSAGE = "The work was cancelled. Start it again when you are ready."


#: A verdict has been reached and written. Nothing may change it afterwards.
#: `cancel_requested` is deliberately absent: that is a request the worker
#: itself still has to honour, and it is still the worker's row to finish.
TERMINAL_EXECUTION_STATUSES: frozenset[ExecutionStatus] = frozenset(
    {"succeeded", "failed", "cancelled", "stale"}
)


def surrendered(status: ExecutionStatus) -> bool:
    """Whether this run has already been given up on by someone else.

    The stalled sweep ends runs it presumes lost, and that presumption is
    sometimes wrong — the worker was slow, not gone. When such a worker finally
    answers, the answer describes a run the system already reported as failed
    and the user may already have retried, so it is kept for tracing and never
    becomes business content.
    """
    return status in TERMINAL_EXECUTION_STATUSES


def cancelled_message(operation: str) -> str:
    """What the user reads when they cancelled one Execution.

    Cancelling is a deliberate act, so every message says the work can start
    again rather than reporting a fault. An operation with no wording of its own
    still gets an answer, because a missing phrase must not fail a cancellation.
    """
    return _CANCELLED_MESSAGES.get(operation, GENERIC_CANCELLED_MESSAGE)
