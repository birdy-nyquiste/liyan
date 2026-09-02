"""Run one 主题知言 analysis inside a durable Execution.

The same shape as `zhiyan/worker.py`, and for the same reasons: the worker owns
no policy, reads the Execution's approved input snapshot, asks the provider, and
admits the answer only through deterministic acceptance. Cancellation, deletion,
and an already-accepted report all win over a late provider result, which stays
retrievable for tracing and never becomes business content.

What differs is what a run reads. A 主题知言 run is approved against a 主题
snapshot, and the snapshot names both the text and the 来源 it was confirmed
beside — so the worker rebuilds those 来源 from the 任务版本 that points at the
snapshot, and refuses to run when what it finds no longer matches.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from liyan_server.database import (
    Database,
    Execution,
    Task,
    TaskVersion,
    ThemeReport,
    ThemeRevision,
)
from liyan_server.execution_dispatch import ExecutionDispatcher
from liyan_server.execution_states import cancelled_message, surrendered
from liyan_server.metering import record_execution_cost
from liyan_server.observability import log_execution_failed
from liyan_server.task_api import version_source_revisions
from liyan_server.theme.acceptance import accept_theme_report_text
from liyan_server.theme.orchestration import (
    accepted_theme_report,
    dispatch_or_fail,
    queue_run,
)
from liyan_server.theme.prompt import AnalysedSource, AnalysedTheme, theme_request
from liyan_server.theme.revisions import context_hash_of
from liyan_server.theme.runs import (
    THEME_OPERATION,
    InvalidRunSnapshot,
    ThemeRunSnapshot,
)
from liyan_server.zhiyan.failures import ZhiyanRunFailure
from liyan_server.zhiyan.provider import (
    SearchAction,
    ZhiyanProvider,
    ZhiyanProviderResult,
)
from liyan_server.zhiyan.recovery import automatic_attempt_permitted, retry_allowed_at

CANCELLED_MESSAGE = cancelled_message(THEME_OPERATION)
UNREADABLE_RUN_MESSAGE = "主题知言请求已失效，请重新发起。"


def process_theme_run(
    database_url: str,
    execution_id: UUID,
    provider: ZhiyanProvider,
    dispatcher: ExecutionDispatcher,
) -> None:
    database = Database(database_url)
    if database.engine is None:
        raise RuntimeError("Database is not configured.")
    try:
        claimed = _claim(database, execution_id)
        if claimed is None:
            return
        snapshot, theme = claimed
        result: ZhiyanProviderResult | None = None
        try:
            result = provider.analyze(
                theme_request(
                    theme,
                    model=snapshot.model,
                    now=snapshot.requested_at,
                    tool_policy=snapshot.tool_policy,
                    prompt_version=snapshot.prompt_version,
                )
            )
            document = accept_theme_report_text(
                result.report_text, opened_urls=result.opened_urls
            )
        except ZhiyanRunFailure as failure:
            _finish_failed(database, execution_id, failure, dispatcher, result=result)
            return
        _finish_succeeded(database, execution_id, snapshot, result, document.model_dump())
    finally:
        database.dispose()


def _analysed_theme(session: Session, revision: ThemeRevision) -> AnalysedTheme | None:
    """The snapshot and the 来源 it was confirmed beside, or None if they disagree.

    The 来源 come from a 任务版本 pointing at this snapshot rather than from the
    snapshot itself, because a snapshot stores their digest and not their text.
    A version whose 来源 no longer hash to that digest cannot be what this run
    was approved for, so the run fails rather than analysing something else.
    """
    version = session.scalar(
        select(TaskVersion)
        .join(Task, Task.id == TaskVersion.task_id)
        .where(
            TaskVersion.theme_revision_id == revision.id,
            Task.deleted_at.is_(None),
        )
        .order_by(TaskVersion.number)
    )
    if version is None:
        return None
    revisions = version_source_revisions(session, version.id)
    if not revisions or context_hash_of(revisions) != revision.source_context_hash:
        return None
    return AnalysedTheme(
        id=str(revision.id),
        content=revision.content,
        content_hash=revision.content_hash,
        source_context_hash=revision.source_context_hash,
        sources=tuple(
            AnalysedSource(
                title=source.title,
                body=source.body,
                provenance=source.provenance,
            )
            for source in revisions
        ),
    )


def _claim(
    database: Database,
    execution_id: UUID,
) -> tuple[ThemeRunSnapshot, AnalysedTheme] | None:
    """Move a queued run to running and return the inputs it was approved to use."""
    if database.engine is None:
        raise RuntimeError("Database is not configured.")
    with Session(database.engine) as session:
        execution = session.get(Execution, execution_id)
        if execution is None or execution.status != "queued":
            return None
        try:
            snapshot = ThemeRunSnapshot.from_json(execution.input_snapshot)
        except InvalidRunSnapshot as error:
            _fail_within(
                execution,
                ZhiyanRunFailure("invalid_run_snapshot", UNREADABLE_RUN_MESSAGE, str(error)),
            )
            session.commit()
            return None
        revision = session.get(ThemeRevision, snapshot.theme_revision_id)
        approved = (
            _analysed_theme(session, revision)
            if revision is not None
            and revision.content_hash == snapshot.content_hash
            and revision.source_context_hash == snapshot.source_context_hash
            else None
        )
        if approved is None:
            _fail_within(
                execution,
                ZhiyanRunFailure(
                    "invalid_run_snapshot",
                    UNREADABLE_RUN_MESSAGE,
                    "The approved 主题 snapshot is no longer available.",
                ),
            )
            session.commit()
            return None
        execution.status = "running"
        execution.started_at = datetime.now(UTC)
        session.commit()
        return snapshot, approved


def _finish_failed(
    database: Database,
    execution_id: UUID,
    failure: ZhiyanRunFailure,
    dispatcher: ExecutionDispatcher,
    result: ZhiyanProviderResult | None = None,
) -> None:
    if database.engine is None:
        raise RuntimeError("Database is not configured.")
    follow_up: UUID | None = None
    with Session(database.engine) as session:
        execution = session.get(Execution, execution_id)
        if execution is None:
            return
        if surrendered(execution.status):
            return
        try:
            snapshot: ThemeRunSnapshot | None = ThemeRunSnapshot.from_json(
                execution.input_snapshot
            )
        except InvalidRunSnapshot:
            snapshot = None
        task = _lock_task(session, snapshot) if snapshot is not None else None
        session.refresh(execution)
        if task is None or task.deleted_at is not None:
            execution.cancellation_requested_at = datetime.now(UTC)
        _fail_within(execution, failure)
        if result is not None:
            execution.stale_result = _stale_result(result)
        _record_failed_cost(session, execution, failure, result)
        recovery = _automatic_attempt(session, execution)
        session.commit()
        follow_up = recovery.id if recovery is not None else None
    if follow_up is not None:
        dispatch_or_fail(database, dispatcher, follow_up)


def _automatic_attempt(session: Session, failed: Execution) -> Execution | None:
    """The initial operation's second and last run, created only when one could help."""
    if failed.status != "failed" or failed.error_code is None:
        return None
    if not automatic_attempt_permitted(
        origin=failed.origin,
        attempt=failed.attempt,
        failure_code=failed.error_code,
    ):
        return None
    revision = session.get(ThemeRevision, failed.target_id)
    if revision is None:
        return None
    try:
        snapshot = ThemeRunSnapshot.from_json(failed.input_snapshot)
    except InvalidRunSnapshot:
        return None
    return queue_run(
        session,
        revision,
        owner_id=failed.owner_id,
        model=snapshot.model,
        origin="automatic",
        attempt=failed.attempt + 1,
    )


def _fail_within(execution: Execution, failure: ZhiyanRunFailure) -> None:
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
    snapshot: ThemeRunSnapshot,
    result: ZhiyanProviderResult,
    document: dict[str, object],
) -> None:
    if database.engine is None:
        raise RuntimeError("Database is not configured.")
    now = datetime.now(UTC)
    with Session(database.engine) as session:
        task = _lock_task(session, snapshot)
        execution = session.get(Execution, execution_id)
        if execution is None:
            return
        if surrendered(execution.status):
            execution.status = "stale"
            execution.stale_result = _stale_result(result)
            _record_cost(session, execution, result, chargeable=False)
            session.commit()
            return
        execution.finished_at = now
        if task is None or task.deleted_at is not None or _cancelled(execution):
            execution.status = "cancelled"
            execution.error_code = "cancelled"
            execution.error_message = CANCELLED_MESSAGE
            execution.stale_result = _stale_result(result)
            _record_cost(session, execution, result, chargeable=False)
            session.commit()
            return
        already_accepted = accepted_theme_report(session, snapshot.theme_revision_id)
        if already_accepted is not None:
            execution.status = "stale"
            execution.stale_result = _stale_result(result)
            _record_cost(session, execution, result, chargeable=False)
            session.commit()
            return
        report = ThemeReport(
            execution_id=execution.id,
            owner_id=execution.owner_id,
            theme_revision_id=snapshot.theme_revision_id,
            prompt_version=snapshot.prompt_version,
            model=result.model,
            provider_response_id=result.response_id,
            document=document,
            search_actions=[_action_json(action) for action in result.search_actions],
            created_at=now,
        )
        session.add(report)
        session.flush()
        execution.status = "succeeded"
        execution.result_id = report.id
        _record_cost(session, execution, result, chargeable=True)
        session.commit()


def _record_failed_cost(
    session: Session,
    execution: Execution,
    failure: ZhiyanRunFailure,
    result: ZhiyanProviderResult | None,
) -> None:
    """What a run that produced no 主题知言报告 nevertheless consumed.

    As in 知言: an acceptance failure carries the refused report, a provider
    failure carries its own bill, and the result wins when both are present
    because it is the whole run rather than only what reached the failure.
    """
    record_execution_cost(
        session,
        execution,
        chargeable=False,
        usage=result.usage if result else failure.usage,
        model=result.model if result else failure.model,
        search_calls=(
            sum(1 for action in result.search_actions if action.kind == "search")
            if result
            else failure.search_calls
        ),
    )


def _record_cost(
    session: Session,
    execution: Execution,
    result: ZhiyanProviderResult | None,
    *,
    chargeable: bool,
) -> None:
    record_execution_cost(
        session,
        execution,
        chargeable=chargeable,
        usage=result.usage if result else None,
        model=result.model if result else None,
        search_calls=(
            sum(1 for action in result.search_actions if action.kind == "search")
            if result
            else None
        ),
    )


def _lock_task(session: Session, snapshot: ThemeRunSnapshot) -> Task | None:
    """Serialize result admission with deletion through the owning task row."""
    return session.scalar(
        select(Task)
        .join(ThemeRevision, ThemeRevision.task_id == Task.id)
        .where(ThemeRevision.id == snapshot.theme_revision_id)
        .with_for_update()
    )


def _stale_result(result: ZhiyanProviderResult) -> dict[str, object]:
    """Provider output that may never become a report, kept only for tracing."""
    return {
        "report_text": result.report_text,
        "response_id": result.response_id,
        "model": result.model,
        "search_actions": [_action_json(action) for action in result.search_actions],
    }


def _action_json(action: SearchAction) -> dict[str, object]:
    return {"kind": action.kind, "query": action.query, "url": action.url}


def _cancelled(execution: Execution) -> bool:
    return execution.cancellation_requested_at is not None or execution.status in {
        "cancel_requested",
        "cancelled",
    }
