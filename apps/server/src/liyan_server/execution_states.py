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

ACTIVE_EXECUTION_STATUSES: frozenset[ExecutionStatus] = frozenset(
    {"queued", "running", "cancel_requested"}
)
