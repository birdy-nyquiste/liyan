"""Run one 提炼主题 press inside a durable Execution.

Smaller than the analysis worker, because a proposal is smaller: nothing durable
comes out of it but three lines of text on the row that asked, there is no
immutability to defend, and there is no automatic recovery attempt — pressing the
button again is the retry, and it is the user's to spend.

What it does share is the discipline: the run reads only its Execution's approved
snapshot, its candidates are admitted only through deterministic acceptance, a
cancelled or superseded press never writes, and every call is costed whatever
became of it.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from liyan_server.database import (
    Database,
    Execution,
    SourcePreparation,
    ThemeProposal,
)
from liyan_server.execution_states import cancelled_message, surrendered
from liyan_server.metering import record_execution_cost
from liyan_server.observability import log_execution_failed
from liyan_server.theme.prompt import AnalysedSource
from liyan_server.theme.proposal import (
    ProposedSources,
    ThemeCandidate,
    accept_candidates_text,
    proposal_request,
)
from liyan_server.theme.revisions import source_context_hash
from liyan_server.theme.runs import (
    PROPOSAL_OPERATION,
    InvalidRunSnapshot,
    ProposalRunSnapshot,
)
from liyan_server.zhiyan.failures import ZhiyanRunFailure
from liyan_server.zhiyan.provider import ZhiyanProvider, ZhiyanProviderResult
from liyan_server.zhiyan.recovery import retry_allowed_at

CANCELLED_MESSAGE = cancelled_message(PROPOSAL_OPERATION)
UNREADABLE_RUN_MESSAGE = "主题提炼请求已失效，请重新发起。"


def process_theme_proposal_run(
    database_url: str,
    execution_id: UUID,
    provider: ZhiyanProvider,
) -> None:
    database = Database(database_url)
    if database.engine is None:
        raise RuntimeError("Database is not configured.")
    try:
        claimed = _claim(database, execution_id)
        if claimed is None:
            return
        snapshot, proposed = claimed
        result: ZhiyanProviderResult | None = None
        try:
            result = provider.analyze(
                proposal_request(
                    proposed,
                    model=snapshot.model,
                    now=snapshot.requested_at,
                    prompt_version=snapshot.prompt_version,
                )
            )
            candidates = accept_candidates_text(result.report_text)
        except ZhiyanRunFailure as failure:
            _finish_failed(database, execution_id, failure, result=result)
            return
        _finish_succeeded(database, execution_id, snapshot, result, candidates)
    finally:
        database.dispose()


def session_sources(
    session: Session,
    *,
    owner_id: UUID,
    client_session_id: str,
) -> list[SourcePreparation]:
    """The unconfirmed 来源 of one 任务创建会话, in the order the user added them."""
    return list(
        session.scalars(
            select(SourcePreparation)
            .where(
                SourcePreparation.owner_id == owner_id,
                SourcePreparation.client_session_id == client_session_id,
                SourcePreparation.confirmed_task_id.is_(None),
            )
            .order_by(SourcePreparation.created_at, SourcePreparation.id)
        ).all()
    )


def proposed_sources(
    session: Session,
    *,
    owner_id: UUID,
    client_session_id: str,
) -> ProposedSources | None:
    """What one press may read, or None when the session is not ready to be read.

    Every 来源 must have been captured successfully. A session holding one that
    is still processing or has failed is not a set anybody should pay to analyse,
    and the interface does not offer the button until it is complete.
    """
    sources = session_sources(session, owner_id=owner_id, client_session_id=client_session_id)
    if not sources or any(source.status not in {"ready", "warning"} for source in sources):
        return None
    return ProposedSources(
        client_session_id=client_session_id,
        source_context_hash=source_context_hash(
            [source.content_hash or "" for source in sources]
        ),
        sources=tuple(
            AnalysedSource(
                title=source.title or "",
                body=source.body or "",
                provenance=source.provenance,
            )
            for source in sources
        ),
    )


def _claim(
    database: Database,
    execution_id: UUID,
) -> tuple[ProposalRunSnapshot, ProposedSources] | None:
    if database.engine is None:
        raise RuntimeError("Database is not configured.")
    with Session(database.engine) as session:
        execution = session.get(Execution, execution_id)
        if execution is None or execution.status != "queued":
            return None
        try:
            snapshot = ProposalRunSnapshot.from_json(execution.input_snapshot)
        except InvalidRunSnapshot as error:
            _fail_within(
                execution,
                ZhiyanRunFailure("invalid_run_snapshot", UNREADABLE_RUN_MESSAGE, str(error)),
            )
            session.commit()
            return None
        proposal = session.get(ThemeProposal, snapshot.proposal_id)
        approved = (
            ProposedSources(
                client_session_id=snapshot.client_session_id,
                source_context_hash=snapshot.source_context_hash,
                sources=tuple(
                    AnalysedSource(title=title, body=body, provenance=provenance)
                    for title, body, provenance in snapshot.sources
                ),
            )
            if proposal is not None and snapshot.sources
            else None
        )
        # A 任务创建会话's 来源 are rows, so they may have changed between the press
        # and the run: that press was made against a set that no longer exists,
        # and is refused rather than answered for material the user did not ask
        # about. A 来源编辑会话's are whatever the writer had typed, which the
        # snapshot is the only record of — there is nothing to compare it to.
        live = (
            proposed_sources(
                session,
                owner_id=proposal.owner_id,
                client_session_id=proposal.client_session_id,
            )
            if proposal is not None and snapshot.session_sources
            else None
        )
        stale_session = snapshot.session_sources and (
            live is None or live.source_context_hash != snapshot.source_context_hash
        )
        if proposal is None or approved is None or stale_session:
            _fail_within(
                execution,
                ZhiyanRunFailure(
                    "invalid_run_snapshot",
                    UNREADABLE_RUN_MESSAGE,
                    "The 来源 this press was made against are no longer in the session.",
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
    result: ZhiyanProviderResult | None = None,
) -> None:
    if database.engine is None:
        raise RuntimeError("Database is not configured.")
    with Session(database.engine) as session:
        execution = session.get(Execution, execution_id)
        if execution is None or surrendered(execution.status):
            return
        _fail_within(execution, failure)
        if result is not None:
            execution.stale_result = _stale_result(result)
        record_execution_cost(
            session,
            execution,
            chargeable=False,
            usage=result.usage if result else failure.usage,
            model=result.model if result else failure.model,
            search_calls=None,
        )
        session.commit()


def _finish_succeeded(
    database: Database,
    execution_id: UUID,
    snapshot: ProposalRunSnapshot,
    result: ZhiyanProviderResult,
    candidates: list[ThemeCandidate],
) -> None:
    if database.engine is None:
        raise RuntimeError("Database is not configured.")
    now = datetime.now(UTC)
    with Session(database.engine) as session:
        execution = session.get(Execution, execution_id)
        proposal = session.get(ThemeProposal, snapshot.proposal_id)
        if execution is None:
            return
        if surrendered(execution.status) or proposal is None:
            execution.status = "stale"
            execution.stale_result = _stale_result(result)
            _record_cost(session, execution, result, chargeable=False)
            session.commit()
            return
        execution.finished_at = now
        if _cancelled(execution):
            execution.status = "cancelled"
            execution.error_code = "cancelled"
            execution.error_message = CANCELLED_MESSAGE
            execution.stale_result = _stale_result(result)
            _record_cost(session, execution, result, chargeable=False)
            session.commit()
            return
        proposal.candidates = [candidate.model_dump() for candidate in candidates]
        proposal.updated_at = now
        execution.status = "succeeded"
        execution.result_id = proposal.id
        _record_cost(session, execution, result, chargeable=True)
        session.commit()


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
        search_calls=None,
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


def _stale_result(result: ZhiyanProviderResult) -> dict[str, object]:
    return {
        "report_text": result.report_text,
        "response_id": result.response_id,
        "model": result.model,
    }


def _cancelled(execution: Execution) -> bool:
    return execution.cancellation_requested_at is not None or execution.status in {
        "cancel_requested",
        "cancelled",
    }
