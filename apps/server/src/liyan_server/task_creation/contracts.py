from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from liyan_server.database import Execution
from liyan_server.execution_states import ExecutionStatus


class EditSourceContentRequest(BaseModel):
    title: str
    body: str
    provenance: str | None = None


class SourceWarning(BaseModel):
    code: str
    message: str


class SourceFailure(BaseModel):
    code: str
    message: str


class ExecutionError(BaseModel):
    code: str
    message: str


class RunSearchProgress(BaseModel):
    """How much external checking one run has done, while it is still doing it."""

    searched: int
    opened: int


class ExecutionResponse(BaseModel):
    id: str
    operation: Literal[
        "fetch_url",
        "parse_file",
        "analyze_source",
        "analyze_theme",
        "propose_themes",
        "generate_article",
        "publish_preview",
    ]
    status: ExecutionStatus
    attempt: int
    input_version: int
    trace_id: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancellation_requested_at: datetime | None
    result_id: str | None
    error: ExecutionError | None
    #: What a searching run has done so far, absent until it says. Two counts
    #: and nothing else — never a query or a URL — so this cannot carry text a
    #: provider read back to a browser.
    progress: RunSearchProgress | None


def execution_response(execution: Execution) -> ExecutionResponse:
    error = (
        ExecutionError(code=execution.error_code, message=execution.error_message)
        if execution.error_code and execution.error_message
        else None
    )
    # Both counts or neither: half of a progress line is a worse answer than
    # none, and a run that has reported has reported both.
    progress = (
        RunSearchProgress(
            searched=execution.searched_count,
            opened=execution.opened_count,
        )
        if execution.searched_count is not None and execution.opened_count is not None
        else None
    )
    return ExecutionResponse(
        id=str(execution.id),
        operation=execution.operation,  # type: ignore[arg-type]
        status=execution.status,
        attempt=execution.attempt,
        input_version=execution.input_version,
        trace_id=str(execution.trace_id),
        created_at=execution.created_at,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
        cancellation_requested_at=execution.cancellation_requested_at,
        result_id=str(execution.result_id) if execution.result_id else None,
        error=error,
        progress=progress,
    )
