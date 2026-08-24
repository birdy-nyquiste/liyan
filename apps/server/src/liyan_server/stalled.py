"""Executions whose worker never came back.

A worker killed mid-run — a deploy, an out-of-memory kill, a lost machine —
leaves its Execution `running` and its 来源 or 任务 waiting on an answer that
will never arrive. Nothing else in the system notices: the row looks exactly
like work in progress, and it will look that way forever.

Ending it is a guess about a process nobody can observe, so the guess is made
carefully and only once. The Execution is marked failed with a code of its own,
which lets the existing recovery policy decide whether another run is warranted
rather than reaching that conclusion here. And it is never reopened: every
worker already refuses to write to an Execution it no longer owns, so a late
answer from a process that was merely slow is discarded rather than accepted.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from liyan_server.database import Database, Execution, SourcePreparation, aware_utc
from liyan_server.settings import Settings

logger = logging.getLogger(__name__)

#: Distinct from any provider failure, because the cause is different and so is
#: the fix. It is deliberately absent from the recoverable set in
#: `zhiyan.recovery`: a run that vanished tells us nothing about whether another
#: would survive, so it does not spend the automatic attempt.
STALLED_CODE = "worker_lost"

#: Queued and never claimed. A different cause and a different fix: a message
#: was lost or purged, or it was addressed to a queue no worker consumes, so the
#: answer is a worker or a routing name rather than a dead process.
NEVER_STARTED_CODE = "worker_never_started"

STALLED_MESSAGE = "这次运行没有返回结果，可以重新发起。"

#: What a file or URL 来源's Execution targets, spelled the way the two
#: task-creation modules write it.
SOURCE_PREPARATION_TARGET_TYPE = "source_preparation"


@dataclass(frozen=True)
class StalledPolicy:
    """How long a run may say nothing before it is presumed lost.

    Generous on purpose. 知言 and 立言 both allow five minutes at the provider,
    and calling a slow run dead costs a user their work; calling a dead one slow
    only delays the next sweep.
    """

    timeout: timedelta = timedelta(minutes=30)
    #: How long work may wait unclaimed. A backlog is not a fault — the worker
    #: may simply be busy — so this is generous too; it exists to catch a queue
    #: nobody is consuming, which otherwise waits forever in silence.
    queued_timeout: timedelta = timedelta(minutes=30)


@dataclass
class StalledReport:
    run_id: UUID = field(default_factory=uuid4)
    stalled_executions: int = 0


def policy_from(settings: Settings) -> StalledPolicy:
    return StalledPolicy(
        timeout=timedelta(minutes=settings.stalled_execution_timeout_minutes),
        queued_timeout=timedelta(minutes=settings.unclaimed_execution_timeout_minutes),
    )


def _release_source(session: Session, execution: Execution, now: datetime) -> None:
    """Tell the 来源 too, or it waits on a run that has already been ended.

    A file or URL 来源 shows "processing" until its Execution says otherwise.
    Ending the Execution alone would leave the user watching a spinner for work
    nobody is doing — the exact symptom this sweep exists to stop.
    """
    if execution.target_type != SOURCE_PREPARATION_TARGET_TYPE:
        return
    source = session.get(SourcePreparation, execution.target_id)
    if (
        source is None
        or source.active_execution_id != execution.id
        or source.input_version != execution.input_version
    ):
        return
    source.status = "failure"
    source.failure_code = STALLED_CODE
    source.failure_message = STALLED_MESSAGE
    source.updated_at = now


def recover_stalled_executions(
    database_url: str, *, policy: StalledPolicy, now: datetime
) -> StalledReport:
    """End every run that has waited too long to still be waiting.

    Two ways that happens, and they are worth telling apart. A `running` run
    whose worker died is the obvious one. A `queued` run nobody ever claimed is
    the quieter one: never claimed means never `running`, so a sweep that looked
    only at runs in flight would never see it, and the 来源 shows 处理中 until
    somebody thinks to look inside the broker.
    """
    database = Database(database_url)
    if database.engine is None:
        raise RuntimeError("Database is not configured.")
    report = StalledReport()
    cutoff = now - policy.timeout
    queued_cutoff = now - policy.queued_timeout
    try:
        with Session(database.engine) as session:
            waiting = session.scalars(
                select(Execution).where(Execution.status.in_(("running", "queued")))
            ).all()
            for execution in waiting:
                claimed = execution.status == "running"
                since = execution.started_at if claimed else execution.created_at
                limit = cutoff if claimed else queued_cutoff
                # Compared here, not in SQL: SQLite stores these naive.
                if aware_utc(since or execution.created_at) >= limit:
                    continue
                execution.status = "failed"
                execution.error_code = STALLED_CODE if claimed else NEVER_STARTED_CODE
                execution.error_message = STALLED_MESSAGE
                execution.finished_at = now
                _release_source(session, execution, now)
                # One commit each, so an interrupted sweep keeps what it ended.
                session.commit()
                report.stalled_executions += 1
                logger.warning(
                    "execution_presumed_lost",
                    extra={
                        "execution_id": str(execution.id),
                        "operation": execution.operation,
                        "attempt": execution.attempt,
                        "error_code": execution.error_code,
                    },
                )
    finally:
        logger.info(
            "stalled_sweep_finished",
            extra={
                "trace_id": str(report.run_id),
                "stalled_executions": report.stalled_executions,
            },
        )
        database.dispose()
    return report
