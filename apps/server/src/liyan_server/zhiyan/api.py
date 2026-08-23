"""The 知言 boundary for one accepted source Revision and for a whole 任务版本.

A 任务版本 holds one to three source Revisions, each with its own independent run,
so this boundary answers two different questions. Per Revision: what happened to
its run, and what may the user do next. Per 任务版本: are all of its reports in,
because that — and only that — is what opens 立言.
"""

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
    TaskVersion,
    TaskVersionSource,
    User,
    ZhiyanReport,
    aware_utc,
)
from liyan_server.execution_dispatch import ExecutionDispatcher
from liyan_server.execution_states import ACTIVE_EXECUTION_STATUSES
from liyan_server.settings import Settings
from liyan_server.task_api import version_source_revisions
from liyan_server.task_creation.contracts import (
    ExecutionError,
    ExecutionResponse,
    execution_response,
)
from liyan_server.zhiyan.orchestration import (
    accepted_report,
    dispatch_or_fail,
    load_runs,
    queue_run,
)
from liyan_server.zhiyan.recovery import RetryState
from liyan_server.zhiyan.report import ZhiyanReportDocument

type ZhiyanStatus = Literal["absent", "running", "cancelled", "failed", "succeeded"]

IMMUTABLE_MESSAGE = "该来源的知言报告已生成，不能修改或重新生成。"
ACTIVE_MESSAGE = "该来源的知言分析正在进行中。"
RATE_LIMITED_MESSAGE = "重试次数已用完，请稍后再试。"
#: The only thing a user is told about a failed run, whatever really went wrong.
BUSY_MESSAGE = "服务繁忙，请重试。"
WAITING_MESSAGE = "知言分析尚未全部完成，全部报告成功后才能生成立言。"
INCOMPLETE_MESSAGE = "仍有来源没有成功的知言报告，全部成功后才能生成立言。"
HISTORICAL_MESSAGE = "历史任务版本只读，恢复为当前版本后才能继续操作。"


class ZhiyanRetryState(BaseModel):
    """Retry timing the server owns; the client only counts down to it."""

    allowed: bool
    remaining: int
    allowed_at: datetime | None

    @classmethod
    def of(cls, retry: RetryState) -> "ZhiyanRetryState":
        return cls(
            allowed=retry.allowed,
            remaining=retry.remaining,
            allowed_at=retry.allowed_at,
        )


class ZhiyanCapabilities(BaseModel):
    can_start: bool
    can_cancel: bool
    retry: ZhiyanRetryState


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


class LiyanCapabilities(BaseModel):
    can_generate: bool
    unavailable_reason: str | None


class TaskVersionZhiyanResponse(BaseModel):
    task_id: str
    task_version_id: str
    task_version_number: int
    sources: list[ZhiyanStateResponse]
    liyan: LiyanCapabilities


def report_response(report: ZhiyanReport) -> ZhiyanReportResponse:
    return ZhiyanReportResponse(
        id=str(report.id),
        source_revision_id=str(report.source_revision_id),
        prompt_version=report.prompt_version,
        model=report.model,
        created_at=aware_utc(report.created_at),
        document=ZhiyanReportDocument.model_validate(report.document),
    )


def zhiyan_execution_response(execution: Execution) -> ExecutionResponse:
    """The run as a browser may see it, never carrying why it really failed.

    Function Spec §5.4 gives the user one sentence for every failure, so the real
    error code stays in the Execution for operators. A cancellation is the user's
    own act, so it keeps its own wording.
    """
    response = execution_response(execution)
    if execution.status not in {"failed", "stale"}:
        return response
    return response.model_copy(update={"error": ExecutionError(code="busy", message=BUSY_MESSAGE)})


def zhiyan_state_response(
    revision: SourceRevision,
    report: ZhiyanReport | None,
    execution: Execution | None,
    retry: RetryState,
    *,
    allow_actions: bool = True,
) -> ZhiyanStateResponse:
    active = execution is not None and execution.status in ACTIVE_EXECUTION_STATUSES
    return ZhiyanStateResponse(
        source_revision_id=str(revision.id),
        source_title=revision.title,
        status=_status(report, execution, active=active),
        report=report_response(report) if report else None,
        execution=zhiyan_execution_response(execution) if execution else None,
        capabilities=ZhiyanCapabilities(
            can_start=allow_actions
            and (report is None and not active and (execution is None or retry.allowed)),
            can_cancel=allow_actions and active,
            retry=ZhiyanRetryState.of(retry),
        ),
    )


def liyan_capabilities(sources: list[ZhiyanStateResponse]) -> LiyanCapabilities:
    """立言 opens only once every source Revision of this version has its report."""
    if sources and all(source.status == "succeeded" for source in sources):
        return LiyanCapabilities(can_generate=True, unavailable_reason=None)
    waiting = any(source.status == "running" for source in sources)
    return LiyanCapabilities(
        can_generate=False,
        unavailable_reason=WAITING_MESSAGE if waiting else INCOMPLETE_MESSAGE,
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
        for_update: bool = False,
    ) -> SourceRevision:
        statement = (
            select(SourceRevision)
            .join(Source, Source.id == SourceRevision.source_id)
            .join(Task, Task.id == Source.task_id)
            .where(
                SourceRevision.id == source_revision_id,
                Task.owner_id == owner_id,
                Task.deleted_at.is_(None),
            )
        )
        if for_update:
            statement = statement.with_for_update(of=Task)
        revision = session.scalar(statement)
        if revision is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source revision not found.",
            )
        return revision

    def state_of(
        session: Session,
        revision: SourceRevision,
        now: datetime,
        *,
        allow_actions: bool = True,
    ) -> ZhiyanStateResponse:
        runs = load_runs(session, revision.id)
        return zhiyan_state_response(
            revision,
            accepted_report(session, revision.id),
            runs.latest,
            runs.retry_state(now),
            allow_actions=allow_actions,
        )

    def is_current_revision(session: Session, revision: SourceRevision) -> bool:
        current = session.scalar(
            select(TaskVersionSource.source_revision_id)
            .join(Task, Task.current_version_id == TaskVersionSource.task_version_id)
            .join(Source, Source.task_id == Task.id)
            .where(
                TaskVersionSource.source_revision_id == revision.id,
                Source.id == revision.source_id,
                Task.deleted_at.is_(None),
            )
        )
        return current is not None

    def require_current_revision(session: Session, revision: SourceRevision) -> None:
        if not is_current_revision(session, revision):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=HISTORICAL_MESSAGE,
            )

    def version_response(
        session: Session,
        task: Task,
        version: TaskVersion,
    ) -> TaskVersionZhiyanResponse:
        current = task.current_version_id == version.id
        now = datetime.now(UTC)
        sources = [
            state_of(session, revision, now, allow_actions=current)
            for revision in version_source_revisions(session, version.id)
        ]
        return TaskVersionZhiyanResponse(
            task_id=str(task.id),
            task_version_id=str(version.id),
            task_version_number=version.number,
            sources=sources,
            liyan=(
                liyan_capabilities(sources)
                if current
                else LiyanCapabilities(
                    can_generate=False,
                    unavailable_reason=HISTORICAL_MESSAGE,
                )
            ),
        )

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
            for_update=True,
        )
        require_current_revision(session, revision)
        if accepted_report(session, revision.id) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=IMMUTABLE_MESSAGE,
            )
        runs = load_runs(session, revision.id)
        previous = runs.latest
        if previous is not None and previous.status in ACTIVE_EXECUTION_STATUSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ACTIVE_MESSAGE)
        now = datetime.now(UTC)
        retry = runs.retry_state(now)
        if previous is not None and not retry.allowed:
            # The server owns retry timing; the client may only count down to it.
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=RATE_LIMITED_MESSAGE,
                headers=_retry_after(retry, now),
            )
        execution = queue_run(
            session,
            revision,
            owner_id=user.id,
            model=settings.zhiyan_model,
            origin="manual" if previous is not None else "initial",
            attempt=previous.attempt + 1 if previous else 1,
            now=now,
        )
        try:
            session.commit()
        except IntegrityError as error:
            # One active 知言 run per source Revision is a database rule, not a check-then-act.
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ACTIVE_MESSAGE,
            ) from error
        dispatch_or_fail(database, dispatcher, execution.id)
        session.expire_all()
        return state_of(session, revision, now)

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
        return state_of(
            session,
            revision,
            datetime.now(UTC),
            allow_actions=is_current_revision(session, revision),
        )

    @router.get(
        "/tasks/{task_id}/versions/{version_id}/zhiyan",
        operation_id="get_task_version_zhiyan",
        response_model=TaskVersionZhiyanResponse,
        tags=["zhiyan"],
    )
    def get_task_version_zhiyan(
        task_id: UUID,
        version_id: UUID,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> TaskVersionZhiyanResponse:
        task = session.scalar(
            select(Task).where(
                Task.id == task_id,
                Task.owner_id == user.id,
                Task.number.is_not(None),
                Task.deleted_at.is_(None),
            )
        )
        version = session.scalar(
            select(TaskVersion).where(
                TaskVersion.id == version_id,
                TaskVersion.task_id == task_id,
            )
        )
        if task is None or version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
        return version_response(session, task, version)

    @router.get(
        "/tasks/{task_id}/zhiyan",
        operation_id="get_task_zhiyan",
        response_model=TaskVersionZhiyanResponse,
        tags=["zhiyan"],
    )
    def get_task_zhiyan(
        task_id: UUID,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> TaskVersionZhiyanResponse:
        """Every 知言 run of the task's current 任务版本, and whether 立言 may open."""
        task = session.scalar(
            select(Task).where(
                Task.id == task_id,
                Task.owner_id == user.id,
                Task.number.is_not(None),
                Task.deleted_at.is_(None),
            )
        )
        version = (
            session.get(TaskVersion, task.current_version_id)
            if task is not None and task.current_version_id is not None
            else None
        )
        if task is None or version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
        return version_response(session, task, version)

    return router


def _retry_after(retry: RetryState, now: datetime) -> dict[str, str]:
    if retry.allowed_at is None:
        return {}
    seconds = max(1, int((retry.allowed_at - now).total_seconds()))
    return {"Retry-After": str(seconds)}
