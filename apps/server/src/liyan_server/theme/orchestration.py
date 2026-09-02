"""Queueing and reading the 主题 runs of one 任务版本.

A 任务版本 has at most one 主题, so unlike 知言 there is nothing here to fan out
across. What this module owns instead is the two things a 主题 run shares with a
知言 run — the same recovery policy applied by both API and worker, and the same
"queue after the transaction commits" discipline — plus the one rule that is its
own: a 主题 snapshot already holding a report is never analysed again, which is
what makes an unchanged 主题 free across versions.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from liyan_server.database import (
    Database,
    Execution,
    ThemeReport,
    ThemeRevision,
    aware_utc,
)
from liyan_server.execution_dispatch import ExecutionDispatcher
from liyan_server.execution_states import RunOrigin
from liyan_server.theme.runs import (
    PROPOSAL_OPERATION,
    THEME_OPERATION,
    new_theme_execution,
)
from liyan_server.zhiyan.orchestration import RevisionRuns
from liyan_server.zhiyan.provider import ToolPolicy

logger = logging.getLogger(__name__)

DISPATCH_FAILED_MESSAGE = "分析未能启动，请重试。"
PROPOSAL_DISPATCH_FAILED_MESSAGE = "主题提炼未能启动，请重试。"


def accepted_theme_report(session: Session, theme_revision_id: UUID) -> ThemeReport | None:
    return session.scalar(
        select(ThemeReport).where(ThemeReport.theme_revision_id == theme_revision_id)
    )


def load_runs(session: Session, theme_revision_id: UUID) -> RevisionRuns:
    """Every 主题知言 run one snapshot has had, read once for both questions.

    `RevisionRuns` is 知言's, and deliberately reused: what happened last and
    what a manual retry may do now are the same two questions with the same
    answer shape, and a second copy of that dataclass would be a second place
    for the retry rule to drift.
    """
    runs = list(session.scalars(_runs_for(theme_revision_id, THEME_OPERATION)).all())
    return RevisionRuns(
        latest=max(runs, key=lambda run: (run.attempt, run.created_at)) if runs else None,
        manual_run_times=tuple(
            aware_utc(run.created_at) for run in runs if run.origin == "manual"
        ),
    )


def load_proposal_runs(session: Session, proposal_id: UUID) -> RevisionRuns:
    runs = list(session.scalars(_runs_for(proposal_id, PROPOSAL_OPERATION)).all())
    return RevisionRuns(
        latest=max(runs, key=lambda run: (run.attempt, run.created_at)) if runs else None,
        manual_run_times=(),
    )


def queue_run(
    session: Session,
    revision: ThemeRevision,
    *,
    owner_id: UUID,
    model: str,
    origin: RunOrigin,
    attempt: int,
    now: datetime | None = None,
) -> Execution:
    """Add one queued 主题知言 run. The caller commits and then dispatches it."""
    execution = new_theme_execution(
        revision,
        owner_id=owner_id,
        model=model,
        tool_policy=ToolPolicy(),
        attempt=attempt,
        origin=origin,
        created_at=now or datetime.now(UTC),
    )
    session.add(execution)
    return execution


def queue_initial_run(
    database: Database,
    dispatcher: ExecutionDispatcher,
    *,
    theme_revision_id: UUID | None,
    owner_id: UUID,
    model: str,
) -> None:
    """Start the 主题知言 run of a just-created 任务版本, in its own transaction.

    Same rule as 知言's `queue_initial_runs`: a 主题 failure never rolls back the
    版本 that was just created, so this runs after that transaction commits and
    swallows its own trouble. A snapshot that already holds a report or a run
    queues nothing, which is what makes a repeated confirmation idempotent and
    an unchanged 主题 free.
    """
    if theme_revision_id is None or database.engine is None:
        return
    queued: UUID | None = None
    try:
        with Session(database.engine) as session:
            revision = session.get(ThemeRevision, theme_revision_id)
            if revision is None:
                return
            if accepted_theme_report(session, revision.id) is not None:
                return
            if load_runs(session, revision.id).latest is not None:
                return
            execution = queue_run(
                session,
                revision,
                owner_id=owner_id,
                model=model,
                origin="initial",
                attempt=1,
            )
            try:
                session.commit()
            except IntegrityError:
                # A concurrent save already queued this snapshot's run.
                session.rollback()
                return
            queued = execution.id
    except Exception:
        logger.exception("theme_initial_queue_failed", extra={"owner_id": str(owner_id)})
    if queued is not None:
        dispatch_or_fail(database, dispatcher, queued)


def dispatch_or_fail(
    database: Database,
    dispatcher: ExecutionDispatcher,
    execution_id: UUID,
    *,
    operation: str = THEME_OPERATION,
) -> None:
    """Hand a queued run to the queue, and fail it visibly when the queue refuses."""
    try:
        dispatcher.dispatch(execution_id, operation)
    except Exception as error:
        logger.exception("theme_dispatch_failed", extra={"execution_id": str(execution_id)})
        if database.engine is None:
            return
        now = datetime.now(UTC)
        with Session(database.engine) as session:
            execution = session.get(Execution, execution_id)
            if execution is None or execution.status != "queued":
                return
            execution.status = "failed"
            execution.error_code = "dispatch_failed"
            execution.error_message = (
                PROPOSAL_DISPATCH_FAILED_MESSAGE
                if operation == PROPOSAL_OPERATION
                else DISPATCH_FAILED_MESSAGE
            )
            execution.internal_error = repr(error)
            execution.finished_at = now
            execution.retry_allowed_at = now
            session.commit()


def _runs_for(target_id: UUID, operation: str) -> Select[tuple[Execution]]:
    return select(Execution).where(
        Execution.target_id == target_id,
        Execution.operation == operation,
    )
