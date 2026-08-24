"""Removing what nobody needs any more, on a schedule and without being asked.

This is the only code in 立言阁 that deletes business data no user pointed at,
so it is written to be dull: every sweep decides from a row's own state, never
from how long the scan has been running, and each item is committed on its own.
An interrupted scan therefore leaves finished work finished and the rest for the
next run, and running twice removes nothing extra.

What it must never take is the evidence of a Blog submission. 发布任务 rows carry
plain identifiers rather than foreign keys precisely so that deleting a 立言任务
cannot reach them, and nothing here goes looking for them either.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from liyan_server.database import (
    Database,
    Execution,
    FileParseResult,
    LiyanArticle,
    LiyanRevision,
    LiyanRunResult,
    Source,
    SourceEditSession,
    SourcePreparation,
    SourceRevision,
    Task,
    TaskVersion,
    TaskVersionSource,
    UrlFetchResult,
    ZhiyanReport,
    aware_utc,
)
from liyan_server.execution_states import ACTIVE_EXECUTION_STATUSES
from liyan_server.liyan.runs import LIYAN_TARGET_TYPE
from liyan_server.object_storage import ObjectStorage
from liyan_server.settings import Settings
from liyan_server.zhiyan.runs import ZHIYAN_TARGET_TYPE

logger = logging.getLogger(__name__)

#: What a file or URL 来源's Execution targets. Spelled here because the two
#: task-creation modules write it as a literal and neither exports it.
SOURCE_PREPARATION_TARGET_TYPE = "source_preparation"

#: The key namespace this server writes uploads under. The orphan sweep stays
#: inside it: a bucket may hold objects that are somebody else's business, and
#: "no row names it" is only evidence of abandonment for keys we create.
MANAGED_KEY_PREFIX = "users/"


@dataclass(frozen=True)
class CleanupPolicy:
    """How long each kind of leftover is kept before it is nobody's.

    The defaults are deliberately generous for anything a user might still be
    looking at. `deleted_task_retention` is different in kind: 30 days is the
    retention the product promises, so shortening it shortens how long "what did
    I submit?" can be answered, rather than just saving disk.
    """

    #: A 任务创建会话 nobody has touched. Long enough to survive a lunch break.
    task_creation_session: timedelta = timedelta(hours=24)
    #: A 来源编辑会话 that was discarded, or left open and forgotten.
    source_edit_session: timedelta = timedelta(hours=24)
    #: How long a deleted 立言任务's business data stays physically present.
    deleted_task_retention: timedelta = timedelta(days=30)


def policy_from(settings: Settings) -> CleanupPolicy:
    """The configured policy, so the schedule and the rules stay one decision."""
    return CleanupPolicy(
        task_creation_session=timedelta(hours=settings.cleanup_task_creation_session_ttl_hours),
        source_edit_session=timedelta(hours=settings.cleanup_source_edit_session_ttl_hours),
        deleted_task_retention=timedelta(days=settings.cleanup_deleted_task_retention_days),
    )


@dataclass
class CleanupReport:
    """What one run removed, per category, for the log line and for tests."""

    run_id: UUID = field(default_factory=uuid4)
    expired_task_creation_sources: int = 0
    expired_source_edit_sessions: int = 0
    purged_tasks: int = 0
    removed_objects: int = 0
    #: Whether R2 answered this run. False means anything holding an object was
    #: left for a later run rather than deleted with its only pointer.
    storage_ready: bool = True


def run_cleanup(
    database_url: str,
    storage: ObjectStorage,
    *,
    policy: CleanupPolicy,
    now: datetime,
) -> CleanupReport:
    """Run every sweep once, in an order where each one's leftovers are next.

    `now` is passed in rather than read, so a run is a pure function of the
    database, the bucket, and one moment — which is what makes the schedule an
    operational detail instead of something the behaviour depends on.
    """
    database = Database(database_url)
    if database.engine is None:
        raise RuntimeError("Database is not configured.")
    report = CleanupReport()
    # Asked once, so every sweep in this run agrees about it. An unconfigured or
    # unreachable bucket is not a reason to stop: the row sweeps have nothing to
    # do with R2 and still run.
    report.storage_ready = storage.state() == "ready"
    if not report.storage_ready:
        logger.warning(
            "cleanup_skipping_object_storage",
            extra={"cleanup_run_id": str(report.run_id), "object_storage": storage.state()},
        )
    try:
        with Session(database.engine) as session:
            _expire_task_creation_sources(session, storage, report, policy=policy, now=now)
            _expire_source_edit_sessions(session, report, policy=policy, now=now)
            _purge_deleted_tasks(session, storage, report, policy=policy, now=now)
            # Last, so it sees the rows the earlier sweeps have already removed.
            _collect_orphaned_objects(session, storage, report, policy=policy, now=now)
    finally:
        # Logged even when a sweep raised. Each item was committed on its own, so
        # a failed run still did real work, and an operator reading a traceback
        # with no counts cannot tell how much.
        logger.info(
            "cleanup_finished",
            extra={
                "cleanup_run_id": str(report.run_id),
                "expired_task_creation_sources": report.expired_task_creation_sources,
                "expired_source_edit_sessions": report.expired_source_edit_sessions,
                "purged_tasks": report.purged_tasks,
                "removed_objects": report.removed_objects,
            },
        )
        database.dispose()
    return report


def _expire_task_creation_sources(
    session: Session,
    storage: ObjectStorage,
    report: CleanupReport,
    *,
    policy: CleanupPolicy,
    now: datetime,
) -> None:
    """Drop 来源 prepared for a 立言任务 that was never confirmed.

    Only unconfirmed ones: once a 来源 belongs to a task it is business data and
    ages with the task, not with the browser session that uploaded it. A 来源
    whose parse is still queued or running is left alone too — the worker is
    about to write to it, and it has not been abandoned yet.
    """
    cutoff = now - policy.task_creation_session
    unconfirmed = session.scalars(
        select(SourcePreparation).where(SourcePreparation.confirmed_task_id.is_(None))
    ).all()
    for source in unconfirmed:
        # Compared here rather than in SQL: SQLite stores these naive, so the
        # database would compare a bare timestamp against an offset one.
        if aware_utc(source.updated_at) >= cutoff:
            continue
        if _has_active_execution(session, source):
            continue
        if source.object_key and not report.storage_ready:
            # Deleting the row now would throw away the only record of the key,
            # leaving the object to be found by listing later, or never.
            continue
        _forget_object(storage, source.object_key, report)
        # The 来源 points at the Execution that prepared it, so it has to let go
        # before that Execution can be deleted.
        source.active_execution_id = None
        source.accepted_result_id = None
        session.flush()
        _delete_executions(session, SOURCE_PREPARATION_TARGET_TYPE, [source.id])
        session.delete(source)
        # One commit per source: an interruption keeps what it finished.
        session.commit()
        report.expired_task_creation_sources += 1


#: Editing checkpoints cleanup may collect once they are old enough. `active`
#: is here because an abandoned tab never leaves any other trace; `saved` is
#: absent because it records which checkpoint produced a 任务版本, and that is
#: history rather than leftovers.
_COLLECTABLE_EDIT_STATUSES: frozenset[str] = frozenset({"active", "discarded"})


def _expire_source_edit_sessions(
    session: Session,
    report: CleanupReport,
    *,
    policy: CleanupPolicy,
    now: datetime,
) -> None:
    """Drop editing checkpoints that were discarded, or simply abandoned.

    A closed tab leaves no mark, so an abandoned session and one being edited
    look identical apart from age — which is the only thing that can separate
    them. Nothing is lost either way: ADR-0003 keeps the working copy in the
    browser, and this row was never a recoverable draft.
    """
    cutoff = now - policy.source_edit_session
    stale = session.scalars(
        select(SourceEditSession).where(SourceEditSession.status.in_(_COLLECTABLE_EDIT_STATUSES))
    ).all()
    for edit in stale:
        if aware_utc(edit.updated_at) >= cutoff:
            continue
        session.delete(edit)
        session.commit()
        report.expired_source_edit_sessions += 1


def _purge_deleted_tasks(
    session: Session,
    storage: ObjectStorage,
    report: CleanupReport,
    *,
    policy: CleanupPolicy,
    now: datetime,
) -> None:
    """Physically remove 立言任务 whose retention window has closed.

    Deletion hid the task the moment the user asked; this is the separate, later
    act that removes it. The window is not a recovery path — nothing exposes a
    deleted task while it waits — it is the room to answer questions about what
    was submitted before the rows are gone.
    """
    cutoff = now - policy.deleted_task_retention
    deleted = session.scalars(select(Task).where(Task.deleted_at.is_not(None))).all()
    for task in deleted:
        if task.deleted_at is None or aware_utc(task.deleted_at) >= cutoff:
            continue
        if _purge_one_task(session, storage, task, report):
            report.purged_tasks += 1


def _purge_one_task(
    session: Session,
    storage: ObjectStorage,
    task: Task,
    report: CleanupReport,
) -> bool:
    """Delete one task's business data child-first, then the task itself.

    Answers whether it did: a task holding objects is left intact when storage
    cannot be reached, rather than half-removed.

    Every row is named explicitly rather than left to `ON DELETE CASCADE`. Two
    reasons: SQLite does not enforce foreign keys unless asked, so a cascade
    would do nothing under test and everything in production; and the rows this
    must *not* reach — 发布任务 and the Executions that attempted them — are
    excluded by construction here rather than by the absence of a constraint.
    """
    version_ids = list(
        session.scalars(select(TaskVersion.id).where(TaskVersion.task_id == task.id))
    )
    source_ids = list(session.scalars(select(Source.id).where(Source.task_id == task.id)))
    revision_ids = list(
        session.scalars(select(SourceRevision.id).where(SourceRevision.source_id.in_(source_ids)))
    )
    article_ids = list(
        session.scalars(
            select(LiyanArticle.id).where(LiyanArticle.task_version_id.in_(version_ids))
        )
    )
    preparations = list(
        session.scalars(
            select(SourcePreparation).where(SourcePreparation.confirmed_task_id == task.id)
        )
    )
    if not report.storage_ready and any(p.object_key for p in preparations):
        # Its retention has already passed; one more cycle costs nothing, and
        # losing track of an object costs a bucket that never empties.
        return False
    for preparation in preparations:
        _forget_object(storage, preparation.object_key, report)
        # Each 来源 points at the Execution that prepared it, and that foreign
        # key has no cascade. Postgres refuses to delete the Execution while the
        # pointer stands; SQLite, which enforces nothing here, would not have
        # told us. Let go first.
        preparation.active_execution_id = None
        preparation.accepted_result_id = None
    session.flush()

    # Only Executions aimed at what is going. A 发布任务's attempts target the
    # 发布任务 itself, so no query here can name them.
    _delete_executions(session, SOURCE_PREPARATION_TARGET_TYPE, [p.id for p in preparations])
    _delete_executions(session, ZHIYAN_TARGET_TYPE, revision_ids)
    _delete_executions(session, LIYAN_TARGET_TYPE, article_ids)
    session.execute(delete(LiyanRevision).where(LiyanRevision.article_id.in_(article_ids)))
    session.execute(delete(LiyanRunResult).where(LiyanRunResult.article_id.in_(article_ids)))
    session.execute(delete(LiyanArticle).where(LiyanArticle.id.in_(article_ids)))
    session.execute(delete(ZhiyanReport).where(ZhiyanReport.source_revision_id.in_(revision_ids)))
    session.execute(
        delete(TaskVersionSource).where(TaskVersionSource.task_version_id.in_(version_ids))
    )
    session.execute(delete(SourceRevision).where(SourceRevision.id.in_(revision_ids)))
    session.execute(delete(Source).where(Source.id.in_(source_ids)))
    session.execute(
        delete(SourcePreparation).where(SourcePreparation.confirmed_task_id == task.id)
    )
    session.execute(delete(SourceEditSession).where(SourceEditSession.task_id == task.id))
    # The task points at its own current version, so that has to let go first.
    task.current_version_id = None
    session.flush()
    session.execute(delete(TaskVersion).where(TaskVersion.id.in_(version_ids)))
    session.delete(task)
    # One commit per task: an interrupted scan leaves whole tasks done or undone.
    session.commit()
    return True


def _collect_orphaned_objects(
    session: Session,
    storage: ObjectStorage,
    report: CleanupReport,
    *,
    policy: CleanupPolicy,
    now: datetime,
) -> None:
    """Remove objects no surviving row names, and only those.

    An upload writes to R2 and then commits its 来源; interrupted in that gap,
    the object is unreachable through every query the server has. So this sweep
    reads the bucket rather than the database, and keeps anything a 来源 still
    points at — including one belonging to a live 立言任务.

    Age is the second half of the rule. Between `put` and its commit a perfectly
    healthy upload looks exactly like an orphan, so nothing recent is touched.
    The grace period borrows the 任务创建会话 TTL rather than adding a dial of its
    own: both answer "how long might this still be somebody's?", and one number
    is easier to reason about than two that must not disagree.
    """
    if not report.storage_ready:
        return
    referenced = {
        key
        for key in session.scalars(
            select(SourcePreparation.object_key).where(SourcePreparation.object_key.is_not(None))
        )
        if key
    }
    cutoff = now - policy.task_creation_session
    for stored in storage.list_objects(MANAGED_KEY_PREFIX):
        if stored.key in referenced or aware_utc(stored.written_at) >= cutoff:
            continue
        storage.delete(stored.key)
        report.removed_objects += 1


def _delete_executions(session: Session, target_type: str, target_ids: Sequence[UUID]) -> None:
    """Remove Executions for these targets, and the results hanging off them.

    `url_fetch_results` and `file_parse_results` cascade from `executions` on
    Postgres and not at all on SQLite, so they are named here: identical
    behaviour on both, and no orphan rows left behind under test.

    `target_type` is matched as well as `target_id` even though ids are unique.
    The point is that this query cannot widen by accident — a 发布任务's
    Executions are excluded by what this asks for, not by luck.
    """
    if not target_ids:
        return
    doomed = select(Execution.id).where(
        Execution.target_type == target_type, Execution.target_id.in_(target_ids)
    )
    session.execute(delete(UrlFetchResult).where(UrlFetchResult.execution_id.in_(doomed)))
    session.execute(delete(FileParseResult).where(FileParseResult.execution_id.in_(doomed)))
    session.execute(
        delete(Execution).where(
            Execution.target_type == target_type, Execution.target_id.in_(target_ids)
        )
    )


def _has_active_execution(session: Session, source: SourcePreparation) -> bool:
    return (
        session.scalar(
            select(Execution.id).where(
                Execution.target_id == source.id,
                Execution.status.in_(ACTIVE_EXECUTION_STATUSES),
            )
        )
        is not None
    )


def _forget_object(storage: ObjectStorage, key: str | None, report: CleanupReport) -> None:
    """Delete the object before the row that names it.

    This order is the one that cannot lose track of anything: a crash after the
    delete leaves a row whose object is already gone, and deleting an absent
    object is a no-op next time. The reverse order leaks the object forever.
    """
    if not key:
        return
    storage.delete(key)
    report.removed_objects += 1
