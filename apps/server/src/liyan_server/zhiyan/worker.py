"""Run one 知言 analysis inside a durable Execution.

The worker owns no policy of its own. It reads the Execution's approved input
snapshot, asks the provider, and admits the answer only through deterministic
acceptance. Cancellation and an already-accepted report both win over a late
provider result, which stays retrievable for tracing but never becomes business
content.

A failed run is also where the initial operation's one automatic recovery attempt
is created, because only here is the real failure reason known. Recovery is the
policy in `recovery`; this module only obeys it.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from liyan_server.database import (
    Database,
    Execution,
    Source,
    SourceRevision,
    Task,
    ZhiyanReport,
)
from liyan_server.execution_dispatch import ExecutionDispatcher
from liyan_server.execution_states import cancelled_message, surrendered
from liyan_server.metering import record_execution_cost
from liyan_server.observability import log_execution_failed
from liyan_server.zhiyan.acceptance import accept_report_text
from liyan_server.zhiyan.failures import ZhiyanRunFailure
from liyan_server.zhiyan.orchestration import dispatch_or_fail, queue_run
from liyan_server.zhiyan.prompt import AcceptedSourceRevision, zhiyan_request
from liyan_server.zhiyan.provider import (
    SearchAction,
    ZhiyanProvider,
    ZhiyanProviderResult,
)
from liyan_server.zhiyan.recovery import automatic_attempt_permitted, retry_allowed_at
from liyan_server.zhiyan.runs import (
    ZHIYAN_OPERATION,
    InvalidRunSnapshot,
    ZhiyanRunSnapshot,
    accepted_revision,
)

CANCELLED_MESSAGE = cancelled_message(ZHIYAN_OPERATION)
UNREADABLE_RUN_MESSAGE = "知言请求已失效，请重新发起。"


def process_zhiyan_run(
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
        snapshot, revision = claimed
        result: ZhiyanProviderResult | None = None
        try:
            result = provider.analyze(
                zhiyan_request(
                    revision,
                    model=snapshot.model,
                    now=snapshot.requested_at,
                    tool_policy=snapshot.tool_policy,
                    prompt_version=snapshot.prompt_version,
                )
            )
            document = accept_report_text(result.report_text, opened_urls=result.opened_urls)
        except ZhiyanRunFailure as failure:
            # `result` is set when the call returned and its report was refused:
            # the provider invoiced that just the same, so it is still a cost.
            _finish_failed(database, execution_id, failure, dispatcher, result=result)
            return
        _finish_succeeded(database, execution_id, snapshot, result, document.model_dump())
    finally:
        database.dispose()


def _claim(
    database: Database,
    execution_id: UUID,
) -> tuple[ZhiyanRunSnapshot, AcceptedSourceRevision] | None:
    """Move a queued run to running and return the inputs it was approved to use."""
    if database.engine is None:
        raise RuntimeError("Database is not configured.")
    with Session(database.engine) as session:
        execution = session.get(Execution, execution_id)
        if execution is None or execution.status != "queued":
            return None
        try:
            snapshot = ZhiyanRunSnapshot.from_json(execution.input_snapshot)
        except InvalidRunSnapshot as error:
            _fail_within(
                execution,
                ZhiyanRunFailure("invalid_run_snapshot", UNREADABLE_RUN_MESSAGE, str(error)),
            )
            session.commit()
            return None
        revision = session.scalar(
            select(SourceRevision)
            .join(Source, Source.id == SourceRevision.source_id)
            .join(Task, Task.id == Source.task_id)
            .where(
                SourceRevision.id == snapshot.source_revision_id,
                Task.deleted_at.is_(None),
            )
        )
        if revision is None or revision.content_hash != snapshot.content_hash:
            _fail_within(
                execution,
                ZhiyanRunFailure(
                    "invalid_run_snapshot",
                    UNREADABLE_RUN_MESSAGE,
                    "The approved source Revision is no longer available.",
                ),
            )
            session.commit()
            return None
        approved = accepted_revision(revision)
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
            # Already ended; re-failing it would overwrite worker_lost with a
            # provider code and could spend an automatic attempt on a run
            # nobody is waiting for.
            return
        try:
            snapshot = ZhiyanRunSnapshot.from_json(execution.input_snapshot)
        except InvalidRunSnapshot:
            snapshot = None
        task = _lock_task(session, snapshot) if snapshot is not None else None
        session.refresh(execution)
        if task is None or task.deleted_at is not None:
            execution.cancellation_requested_at = datetime.now(UTC)
        _fail_within(execution, failure)
        if result is not None:
            # The report that was refused, kept verbatim. Acceptance says which
            # rule it broke; only the text says why, and the two together are
            # what turns a recurring rejection into something anybody can fix.
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
    revision = session.get(SourceRevision, failed.target_id)
    if revision is None:
        return None
    try:
        snapshot = ZhiyanRunSnapshot.from_json(failed.input_snapshot)
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
    snapshot: ZhiyanRunSnapshot,
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
            # Someone already ended this run — the stalled sweep, or a newer run
            # that won. `stale` is the established word for an answer that
            # arrived and was not used; the original error_code is left in place
            # so why it ended is still readable.
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
        already_accepted = session.scalar(
            select(ZhiyanReport).where(
                ZhiyanReport.source_revision_id == snapshot.source_revision_id
            )
        )
        if already_accepted is not None:
            execution.status = "stale"
            execution.stale_result = _stale_result(result)
            _record_cost(session, execution, result, chargeable=False)
            session.commit()
            return
        report = ZhiyanReport(
            execution_id=execution.id,
            owner_id=execution.owner_id,
            source_revision_id=snapshot.source_revision_id,
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
    """What a run that produced no 知言报告 nevertheless consumed.

    Two failures with the same code cost very different amounts, and until this
    existed neither was recorded. An acceptance failure has a `result`, because
    the report came back and was refused. A provider failure has none — it is
    raised inside the adapter, after the call has returned and been invoiced but
    before there is anything to return — so it carries its own bill instead, and
    that is the expensive kind: a run that searched twenty times and wrote no
    report is the most costly thing 知言 does.

    The result wins when both are present. It is the whole run, tallied across
    every call the adapter made; the failure carries only what reached it.
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
    """What this run consumed, whatever became of its report.

    A refused, cancelled, or superseded report was invoiced exactly like an
    accepted one, so all of them are recorded; only an accepted one is
    chargeable. Searches are counted from the actions the provider reported,
    because they are the least predictable term in what a 知言 run costs.
    """
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


def _lock_task(session: Session, snapshot: ZhiyanRunSnapshot) -> Task | None:
    """Serialize result admission with deletion through the owning task row."""
    return session.scalar(
        select(Task)
        .join(Source, Source.task_id == Task.id)
        .join(SourceRevision, SourceRevision.source_id == Source.id)
        .where(SourceRevision.id == snapshot.source_revision_id)
        .with_for_update()
    )


def _stale_result(result: ZhiyanProviderResult) -> dict[str, object]:
    """Provider output that may never become a 知言报告, kept only for tracing.

    Technical Spec §6.4: an expired result stays in the execution record and does
    not overwrite current business data. Nothing returns this to a client.
    """
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
