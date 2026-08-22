"""The 知言 boundary for exactly one accepted source Revision."""

import logging
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from liyan_server.authentication import CurrentUserDependency
from liyan_server.database import (
    Database,
    Execution,
    Source,
    SourceRevision,
    Task,
    User,
    ZhiyanReport,
    aware_utc,
)
from liyan_server.execution_dispatch import ExecutionDispatcher
from liyan_server.execution_states import ACTIVE_EXECUTION_STATUSES
from liyan_server.settings import Settings
from liyan_server.task_creation.contracts import ExecutionResponse, execution_response
from liyan_server.zhiyan.provider import ToolPolicy
from liyan_server.zhiyan.report import ZhiyanReportDocument
from liyan_server.zhiyan.runs import ZHIYAN_OPERATION, new_zhiyan_execution

logger = logging.getLogger(__name__)

type ZhiyanStatus = Literal["absent", "running", "cancelled", "failed", "succeeded"]

IMMUTABLE_MESSAGE = "该来源的知言报告已生成，不能修改或重新生成。"
ACTIVE_MESSAGE = "该来源的知言分析正在进行中。"
DISPATCH_FAILED_MESSAGE = "分析未能启动，请重试。"


class ZhiyanCapabilities(BaseModel):
    can_start: bool
    can_cancel: bool


class ZhiyanReportResponse(BaseModel):
    id: str
    source_revision_id: str
    prompt_version: str
    model: str
    created_at: datetime
    document: ZhiyanReportDocument


class ZhiyanStateResponse(BaseModel):
    source_revision_id: str
    source_title: str
    status: ZhiyanStatus
    report: ZhiyanReportResponse | None
    execution: ExecutionResponse | None
    capabilities: ZhiyanCapabilities


def report_response(report: ZhiyanReport) -> ZhiyanReportResponse:
    return ZhiyanReportResponse(
        id=str(report.id),
        source_revision_id=str(report.source_revision_id),
        prompt_version=report.prompt_version,
        model=report.model,
        created_at=aware_utc(report.created_at),
        document=ZhiyanReportDocument.model_validate(report.document),
    )


def zhiyan_state_response(
    revision: SourceRevision,
    report: ZhiyanReport | None,
    execution: Execution | None,
) -> ZhiyanStateResponse:
    active = execution is not None and execution.status in ACTIVE_EXECUTION_STATUSES
    return ZhiyanStateResponse(
        source_revision_id=str(revision.id),
        source_title=revision.title,
        status=_status(report, execution, active=active),
        report=report_response(report) if report else None,
        execution=execution_response(execution) if execution else None,
        capabilities=ZhiyanCapabilities(
            can_start=report is None and not active,
            can_cancel=active,
        ),
    )


def _status(
    report: ZhiyanReport | None,
    execution: Execution | None,
    *,
    active: bool,
) -> ZhiyanStatus:
    if report is not None:
        return "succeeded"
    if active:
        return "running"
    if execution is None:
        return "absent"
    return "cancelled" if execution.status == "cancelled" else "failed"


def zhiyan_router(
    settings: Settings,
    database: Database,
    current_user: CurrentUserDependency,
    dispatcher: ExecutionDispatcher,
) -> APIRouter:
    router = APIRouter()

    def owned_revision(
        session: Session,
        *,
        source_revision_id: UUID,
        owner_id: UUID,
    ) -> SourceRevision:
        revision = session.scalar(
            select(SourceRevision)
            .join(Source, Source.id == SourceRevision.source_id)
            .join(Task, Task.id == Source.task_id)
            .where(SourceRevision.id == source_revision_id, Task.owner_id == owner_id)
        )
        if revision is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source revision not found.",
            )
        return revision

    def accepted_report(session: Session, revision_id: UUID) -> ZhiyanReport | None:
        return session.scalar(
            select(ZhiyanReport).where(ZhiyanReport.source_revision_id == revision_id)
        )

    def latest_run(session: Session, revision_id: UUID) -> Execution | None:
        return session.scalar(
            select(Execution)
            .where(
                Execution.target_id == revision_id,
                Execution.operation == ZHIYAN_OPERATION,
            )
            .order_by(Execution.attempt.desc(), Execution.created_at.desc())
            .limit(1)
        )

    def dispatch(execution_id: UUID) -> None:
        try:
            dispatcher.dispatch(execution_id)
        except Exception as error:
            logger.exception(
                "zhiyan_dispatch_failed",
                extra={"execution_id": str(execution_id)},
            )
            if database.engine is None:
                return
            with Session(database.engine) as recovery_session:
                execution = recovery_session.get(Execution, execution_id)
                if execution is None or execution.status != "queued":
                    return
                execution.status = "failed"
                execution.error_code = "dispatch_failed"
                execution.error_message = DISPATCH_FAILED_MESSAGE
                execution.internal_error = repr(error)
                execution.finished_at = datetime.now(UTC)
                recovery_session.commit()

    @router.post(
        "/source-revisions/{source_revision_id}/zhiyan-runs",
        operation_id="start_zhiyan_run",
        response_model=ZhiyanStateResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["zhiyan"],
    )
    def start_zhiyan_run(
        source_revision_id: UUID,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> ZhiyanStateResponse:
        revision = owned_revision(
            session,
            source_revision_id=source_revision_id,
            owner_id=user.id,
        )
        if accepted_report(session, revision.id) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=IMMUTABLE_MESSAGE,
            )
        previous = latest_run(session, revision.id)
        if previous is not None and previous.status in ACTIVE_EXECUTION_STATUSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ACTIVE_MESSAGE)
        execution = new_zhiyan_execution(
            revision,
            owner_id=user.id,
            model=settings.zhiyan_model,
            tool_policy=ToolPolicy(),
            attempt=previous.attempt + 1 if previous else 1,
            created_at=datetime.now(UTC),
        )
        session.add(execution)
        try:
            session.commit()
        except IntegrityError as error:
            # One active 知言 run per source Revision is a database rule, not a check-then-act.
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ACTIVE_MESSAGE,
            ) from error
        dispatch(execution.id)
        session.refresh(execution)
        return zhiyan_state_response(revision, accepted_report(session, revision.id), execution)

    @router.get(
        "/source-revisions/{source_revision_id}/zhiyan",
        operation_id="get_zhiyan_state",
        response_model=ZhiyanStateResponse,
        tags=["zhiyan"],
    )
    def get_zhiyan_state(
        source_revision_id: UUID,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> ZhiyanStateResponse:
        revision = owned_revision(
            session,
            source_revision_id=source_revision_id,
            owner_id=user.id,
        )
        return zhiyan_state_response(
            revision,
            accepted_report(session, revision.id),
            latest_run(session, revision.id),
        )

    return router
