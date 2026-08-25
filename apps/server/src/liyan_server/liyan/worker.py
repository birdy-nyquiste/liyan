from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from liyan_server.database import (
    Database,
    Execution,
    LiyanArticle,
    LiyanRunResult,
    Task,
    TaskVersion,
)
from liyan_server.execution_dispatch import ExecutionDispatcher
from liyan_server.execution_states import cancelled_message, surrendered
from liyan_server.liyan.acceptance import GeneratedArticle, accept_article_text
from liyan_server.liyan.failures import LiyanRunFailure
from liyan_server.liyan.orchestration import dispatch_or_fail, queue_run
from liyan_server.liyan.prompt import liyan_request
from liyan_server.liyan.provider import LiyanProvider, LiyanProviderResult
from liyan_server.liyan.recovery import automatic_attempt_permitted, retry_allowed_at
from liyan_server.liyan.runs import (
    LIYAN_OPERATION,
    InvalidRunSnapshot,
    LiyanRunSnapshot,
)
from liyan_server.observability import log_execution_failed
from liyan_server.task_activity import record_task_activity

CANCELLED_MESSAGE = cancelled_message(LIYAN_OPERATION)
UNREADABLE_RUN_MESSAGE = "立言请求已失效，请重新发起。"


def process_liyan_run(
    database_url: str,
    execution_id: UUID,
    provider: LiyanProvider,
    dispatcher: ExecutionDispatcher,
) -> None:
    database = Database(database_url)
    if database.engine is None:
        raise RuntimeError("Database is not configured.")
    try:
        snapshot = _claim(database, execution_id)
        if snapshot is None:
            return
        try:
            result = provider.generate(
                liyan_request(
                    model=snapshot.model,
                    input_text=snapshot.input_text,
                    prompt_version=snapshot.prompt_version,
                )
            )
            article = accept_article_text(result.article_text)
        except LiyanRunFailure as failure:
            _finish_failed(database, execution_id, failure, dispatcher)
            return
        _finish_succeeded(database, execution_id, snapshot, result, article)
    finally:
        database.dispose()


def _claim(database: Database, execution_id: UUID) -> LiyanRunSnapshot | None:
    assert database.engine is not None
    with Session(database.engine) as session:
        execution = session.get(Execution, execution_id)
        if execution is None or execution.status != "queued":
            return None
        try:
            snapshot = LiyanRunSnapshot.from_json(execution.input_snapshot)
        except InvalidRunSnapshot as error:
            _fail_within(
                execution,
                LiyanRunFailure("invalid_run_snapshot", UNREADABLE_RUN_MESSAGE, str(error)),
            )
            session.commit()
            return None
        if not _target_is_current(session, snapshot):
            _fail_within(
                execution,
                LiyanRunFailure(
                    "invalid_run_snapshot",
                    UNREADABLE_RUN_MESSAGE,
                    "The approved task version is no longer current.",
                ),
            )
            session.commit()
            return None
        execution.status = "running"
        execution.started_at = datetime.now(UTC)
        session.commit()
        return snapshot


def _target_is_current(session: Session, snapshot: LiyanRunSnapshot) -> bool:
    article = session.get(LiyanArticle, snapshot.article_id)
    if article is None or article.task_version_id != snapshot.task_version_id:
        return False
    return (
        session.scalar(
            select(Task.id)
            .join(TaskVersion, TaskVersion.task_id == Task.id)
            .where(
                TaskVersion.id == snapshot.task_version_id,
                Task.current_version_id == snapshot.task_version_id,
                Task.deleted_at.is_(None),
            )
        )
        is not None
    )


def _finish_failed(
    database: Database,
    execution_id: UUID,
    failure: LiyanRunFailure,
    dispatcher: ExecutionDispatcher,
) -> None:
    assert database.engine is not None
    follow_up: UUID | None = None
    with Session(database.engine) as session:
        execution = session.get(Execution, execution_id)
        if execution is None:
            return
        if surrendered(execution.status):
            return
        try:
            snapshot = LiyanRunSnapshot.from_json(execution.input_snapshot)
        except InvalidRunSnapshot:
            snapshot = None
        task = _lock_task(session, snapshot) if snapshot is not None else None
        session.refresh(execution)
        if task is None or task.deleted_at is not None:
            execution.cancellation_requested_at = datetime.now(UTC)
        _fail_within(execution, failure)
        recovery = _automatic_attempt(session, execution)
        session.commit()
        follow_up = recovery.id if recovery is not None else None
    if follow_up is not None:
        dispatch_or_fail(database, dispatcher, follow_up)


def _automatic_attempt(session: Session, failed: Execution) -> Execution | None:
    if failed.status != "failed" or failed.error_code is None:
        return None
    if not automatic_attempt_permitted(
        origin=failed.origin, attempt=failed.attempt, failure_code=failed.error_code
    ):
        return None
    article = session.get(LiyanArticle, failed.target_id)
    if article is None:
        return None
    try:
        snapshot = LiyanRunSnapshot.from_json(failed.input_snapshot)
    except InvalidRunSnapshot:
        return None
    return queue_run(
        session,
        article,
        owner_id=failed.owner_id,
        model=snapshot.model,
        input_text=snapshot.input_text,
        instruction=snapshot.instruction,
        working_copy=snapshot.working_copy,
        input_version=failed.input_version,
        attempt=failed.attempt + 1,
        origin="automatic",
        idempotency_key=None,
        request_hash=failed.request_hash or failed.input_identity,
        now=datetime.now(UTC),
    )


def _fail_within(execution: Execution, failure: LiyanRunFailure) -> None:
    cancelled = _cancelled(execution)
    now = datetime.now(UTC)
    execution.status = "cancelled" if cancelled else "failed"
    execution.error_code = "cancelled" if cancelled else failure.code
    execution.error_message = CANCELLED_MESSAGE if cancelled else failure.message
    execution.internal_error = failure.internal_error
    execution.finished_at = now
    execution.retry_allowed_at = None if cancelled else retry_allowed_at(now, failure.code)
    log_execution_failed(
        execution_id=execution.id,
        operation=execution.operation,
        attempt=execution.attempt,
        error_code=execution.error_code,
    )


def _finish_succeeded(
    database: Database,
    execution_id: UUID,
    snapshot: LiyanRunSnapshot,
    provider_result: LiyanProviderResult,
    article: GeneratedArticle,
) -> None:
    assert database.engine is not None
    now = datetime.now(UTC)
    with Session(database.engine) as session:
        task = _lock_task(session, snapshot)
        execution = session.get(Execution, execution_id)
        if execution is None:
            return
        if surrendered(execution.status):
            # Already ended by the stalled sweep or a newer run. Kept for
            # tracing under `stale`, with the original error_code intact.
            execution.status = "stale"
            execution.stale_result = _stale_result(provider_result)
            session.commit()
            return
        execution.finished_at = now
        target_is_current = (
            task is not None
            and task.deleted_at is None
            and task.current_version_id == snapshot.task_version_id
        )
        if _cancelled(execution) or not target_is_current:
            execution.status = "cancelled" if _cancelled(execution) else "stale"
            if _cancelled(execution):
                execution.error_code = "cancelled"
                execution.error_message = CANCELLED_MESSAGE
            execution.stale_result = _stale_result(provider_result)
            session.commit()
            return
        accepted = session.scalar(
            select(LiyanRunResult).where(LiyanRunResult.execution_id == execution.id)
        )
        if accepted is not None:
            return
        run_result = LiyanRunResult(
            execution_id=execution.id,
            owner_id=execution.owner_id,
            article_id=snapshot.article_id,
            task_version_id=snapshot.task_version_id,
            prompt_version=snapshot.prompt_version,
            model=provider_result.model,
            provider_response_id=provider_result.response_id,
            title=article.title,
            body_markdown=article.body_markdown,
            instruction=snapshot.instruction.plain_text(),
            created_at=now,
        )
        session.add(run_result)
        session.flush()
        execution.status = "succeeded"
        execution.result_id = run_result.id
        assert task is not None
        record_task_activity(task, at=now)
        session.commit()


def _lock_task(session: Session, snapshot: LiyanRunSnapshot) -> Task | None:
    """Serialize result admission with deletion through the owning task row."""
    return session.scalar(
        select(Task)
        .join(TaskVersion, TaskVersion.task_id == Task.id)
        .where(TaskVersion.id == snapshot.task_version_id)
        .with_for_update()
    )


def _stale_result(result: LiyanProviderResult) -> dict[str, object]:
    return {
        "article_text": result.article_text,
        "response_id": result.response_id,
        "model": result.model,
    }


def _cancelled(execution: Execution) -> bool:
    return execution.cancellation_requested_at is not None or execution.status in {
        "cancel_requested",
        "cancelled",
    }
