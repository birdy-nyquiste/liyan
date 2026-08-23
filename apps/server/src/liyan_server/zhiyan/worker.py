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

from liyan_server.database import Database, Execution, SourceRevision, ZhiyanReport
from liyan_server.execution_dispatch import ExecutionDispatcher
from liyan_server.execution_states import cancelled_message
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
            _finish_failed(database, execution_id, failure, dispatcher)
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
        revision = session.get(SourceRevision, snapshot.source_revision_id)
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
) -> None:
    if database.engine is None:
        raise RuntimeError("Database is not configured.")
    follow_up: UUID | None = None
    with Session(database.engine) as session:
        execution = session.get(Execution, execution_id)
        if execution is None:
            return
        _fail_within(execution, failure)
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
        execution = session.get(Execution, execution_id)
        if execution is None:
            return
        execution.finished_at = now
        if _cancelled(execution):
            execution.status = "cancelled"
            execution.error_code = "cancelled"
            execution.error_message = CANCELLED_MESSAGE
            execution.stale_result = _stale_result(result)
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
        session.commit()


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
