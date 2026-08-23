"""Queueing and reading 知言 runs across a whole 任务版本.

One 知言报告 belongs to one source Revision, so a 任务版本 with three sources runs
three independent analyses that may succeed, fail, or be cancelled on their own
schedules. This module is where those independent runs are queued and read back
together, so both the API and the worker apply the same recovery policy and the
same 立言 gate: 立言 opens only once every source Revision of the current version
holds an accepted report.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from liyan_server.database import (
    Database,
    Execution,
    SourceRevision,
    ZhiyanReport,
    aware_utc,
)
from liyan_server.execution_dispatch import ExecutionDispatcher
from liyan_server.execution_states import RunOrigin
from liyan_server.zhiyan.provider import ToolPolicy
from liyan_server.zhiyan.recovery import RetryState, retry_state
from liyan_server.zhiyan.runs import ZHIYAN_OPERATION, new_zhiyan_execution

logger = logging.getLogger(__name__)

DISPATCH_FAILED_MESSAGE = "分析未能启动，请重试。"


def accepted_report(session: Session, source_revision_id: UUID) -> ZhiyanReport | None:
    return session.scalar(
        select(ZhiyanReport).where(ZhiyanReport.source_revision_id == source_revision_id)
    )


@dataclass(frozen=True)
class RevisionRuns:
    """Every 知言 run one source Revision has had.

    Both questions a caller asks — what happened last, and what a manual retry
    may do now — are answered from the same rows, so they are read once.
    """

    latest: Execution | None
    manual_run_times: tuple[datetime, ...]

    def retry_state(self, now: datetime) -> RetryState:
        return retry_state(
            now=now,
            manual_run_times=self.manual_run_times,
            earliest_retry_at=(
                aware_utc(self.latest.retry_allowed_at)
                if self.latest is not None and self.latest.retry_allowed_at is not None
                else None
            ),
        )


def load_runs(session: Session, source_revision_id: UUID) -> RevisionRuns:
    runs = list(session.scalars(_runs_for(source_revision_id)).all())
    return RevisionRuns(
        latest=max(runs, key=lambda run: (run.attempt, run.created_at)) if runs else None,
        manual_run_times=tuple(
            aware_utc(run.created_at) for run in runs if run.origin == "manual"
        ),
    )


def queue_run(
    session: Session,
    revision: SourceRevision,
    *,
    owner_id: UUID,
    model: str,
    origin: RunOrigin,
    attempt: int,
    now: datetime | None = None,
) -> Execution:
    """Add one queued 知言 run. The caller commits and then dispatches it."""
    execution = new_zhiyan_execution(
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


def queue_initial_runs(
    database: Database,
    dispatcher: ExecutionDispatcher,
    *,
    source_revision_ids: Sequence[UUID],
    owner_id: UUID,
    model: str,
) -> None:
    """Start one run per source Revision after the task transaction has committed.

    Function Spec §2.1: a 知言 failure never rolls back the formal task, so this
    runs in its own transaction and swallows its own trouble. It also skips any
    Revision that already has a report or a run, which makes a client's repeated
    confirmation queue nothing new.
    """
    if database.engine is None:
        return
    queued: list[UUID] = []
    try:
        with Session(database.engine) as session:
            for source_revision_id in source_revision_ids:
                revision = session.get(SourceRevision, source_revision_id)
                if revision is None:
                    continue
                if accepted_report(session, revision.id) is not None:
                    continue
                if load_runs(session, revision.id).latest is not None:
                    continue
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
                    # A concurrent confirmation already queued this Revision's run.
                    session.rollback()
                    continue
                queued.append(execution.id)
    except Exception:
        logger.exception("zhiyan_initial_queue_failed", extra={"owner_id": str(owner_id)})
    for execution_id in queued:
        dispatch_or_fail(database, dispatcher, execution_id)


def dispatch_or_fail(
    database: Database,
    dispatcher: ExecutionDispatcher,
    execution_id: UUID,
) -> None:
    """Hand a queued run to the queue, and fail it visibly when the queue refuses."""
    try:
        dispatcher.dispatch(execution_id)
    except Exception as error:
        logger.exception("zhiyan_dispatch_failed", extra={"execution_id": str(execution_id)})
        if database.engine is None:
            return
        now = datetime.now(UTC)
        with Session(database.engine) as session:
            execution = session.get(Execution, execution_id)
            if execution is None or execution.status != "queued":
                return
            execution.status = "failed"
            execution.error_code = "dispatch_failed"
            execution.error_message = DISPATCH_FAILED_MESSAGE
            execution.internal_error = repr(error)
            execution.finished_at = now
            execution.retry_allowed_at = now
            session.commit()


def _runs_for(source_revision_id: UUID) -> Select[tuple[Execution]]:
    return select(Execution).where(
        Execution.target_id == source_revision_id,
        Execution.operation == ZHIYAN_OPERATION,
    )
