import hashlib
import json
from contextlib import suppress
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from liyan_server.authentication import CurrentUserDependency
from liyan_server.database import (
    Database,
    Execution,
    LiyanArticle,
    LiyanRunResult,
    Task,
    TaskVersion,
    User,
    ZhiyanReport,
    aware_utc,
)
from liyan_server.execution_dispatch import ExecutionDispatcher
from liyan_server.execution_states import ACTIVE_EXECUTION_STATUSES
from liyan_server.liyan.instruction import (
    InstructionDocument,
    InstructionText,
)
from liyan_server.liyan.orchestration import dispatch_or_fail, load_runs, queue_run
from liyan_server.liyan.prompt import liyan_input_text
from liyan_server.liyan.recovery import RetryState
from liyan_server.liyan.runs import LIYAN_OPERATION
from liyan_server.settings import Settings
from liyan_server.task_api import version_source_revisions
from liyan_server.task_creation.contracts import (
    ExecutionError,
    ExecutionResponse,
    execution_response,
)

type LiyanStatus = Literal["absent", "running", "cancelled", "failed", "succeeded"]

INCOMPLETE_MESSAGE = "全部知言报告成功后才能生成立言。"
ACTIVE_MESSAGE = "立言文章正在生成中。"
RATE_LIMITED_MESSAGE = "重试次数已用完，请稍后再试。"
BUSY_MESSAGE = "服务繁忙，请重试。"
IDEMPOTENCY_MISMATCH = "相同幂等键不能用于不同的立言请求。"
RETRY_INPUT_MISMATCH = "失败重试必须使用原来的 Working Copy 和立言指令。"
INVALID_CAPSULE = "立言指令包含无效或过期的知言引用。"
DUPLICATE_CAPSULE = "立言指令包含重复的知言引用。"


class WorkingCopyInput(BaseModel):
    title: str
    body_markdown: str


class StartLiyanRunRequest(BaseModel):
    idempotency_key: str
    instruction: InstructionDocument = Field(default_factory=InstructionDocument)
    working_copy: WorkingCopyInput | None = None

    @field_validator("instruction", mode="before")
    @classmethod
    def accept_plain_instruction(cls, value: object) -> object:
        return InstructionDocument.from_text(value) if isinstance(value, str) else value


class LiyanRetryState(BaseModel):
    allowed: bool
    remaining: int
    allowed_at: datetime | None

    @classmethod
    def of(cls, retry: RetryState) -> "LiyanRetryState":
        return cls(
            allowed=retry.allowed,
            remaining=retry.remaining,
            allowed_at=retry.allowed_at,
        )


class LiyanRunCapabilities(BaseModel):
    can_generate: bool
    can_cancel: bool
    retry: LiyanRetryState
    unavailable_reason: str | None


class LiyanResultResponse(BaseModel):
    id: str
    execution_id: str
    task_version_id: str
    title: str
    body_markdown: str
    instruction: InstructionDocument
    prompt_version: str
    model: str
    created_at: datetime


class LiyanRunRequestResponse(BaseModel):
    instruction: InstructionDocument
    working_copy: WorkingCopyInput | None


class LiyanStateResponse(BaseModel):
    task_id: str
    task_version_id: str
    status: LiyanStatus
    execution: ExecutionResponse | None
    result: LiyanResultResponse | None
    request: LiyanRunRequestResponse | None
    capabilities: LiyanRunCapabilities


def liyan_router(
    settings: Settings,
    database: Database,
    current_user: CurrentUserDependency,
    dispatcher: ExecutionDispatcher,
) -> APIRouter:
    router = APIRouter()

    def owned_current(
        session: Session, task_id: UUID, owner_id: UUID
    ) -> tuple[Task, TaskVersion]:
        task = session.scalar(
            select(Task).where(
                Task.id == task_id,
                Task.owner_id == owner_id,
                Task.number.is_not(None),
            )
        )
        version = (
            session.get(TaskVersion, task.current_version_id)
            if task is not None and task.current_version_id is not None
            else None
        )
        if task is None or version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
        return task, version

    def complete_context(
        session: Session, version: TaskVersion
    ) -> list[dict[str, object]]:
        revisions = version_source_revisions(session, version.id)
        context: list[dict[str, object]] = []
        for revision in revisions:
            report = session.scalar(
                select(ZhiyanReport).where(
                    ZhiyanReport.source_revision_id == revision.id
                )
            )
            if report is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=INCOMPLETE_MESSAGE,
                )
            context.append(
                {
                    "source": {
                        "title": revision.title,
                        "body": revision.body,
                        "provenance": revision.provenance,
                    },
                    "zhiyan_report": report.document,
                }
            )
        if not context:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=INCOMPLETE_MESSAGE
            )
        return context

    def resolve_instruction(
        session: Session,
        version: TaskVersion,
        instruction: InstructionDocument,
    ) -> tuple[list[dict[str, object]], dict[str, object]]:
        current_revision_ids = {
            revision.id for revision in version_source_revisions(session, version.id)
        }
        seen: set[tuple[UUID, str]] = set()
        resolved: list[dict[str, object]] = []
        model_parts: list[dict[str, object]] = []
        for part in instruction.content:
            if isinstance(part, InstructionText):
                model_parts.append(part.model_dump())
                continue
            if part.identity in seen:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=DUPLICATE_CAPSULE,
                )
            seen.add(part.identity)
            report = session.get(ZhiyanReport, part.report_id)
            if (
                part.task_version_id != version.id
                or report is None
                or report.source_revision_id not in current_revision_ids
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=INVALID_CAPSULE,
                )
            item = _report_item(report.document, part.item_id)
            if item is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=INVALID_CAPSULE,
                )
            kind, content = item
            number = len(resolved) + 1
            resolved.append({"capsule": number, "kind": kind, "content": content})
            model_parts.append({"type": "capsule", "capsule": number})
        return resolved, {"content": model_parts}

    def article_for(
        session: Session, version: TaskVersion, owner_id: UUID
    ) -> LiyanArticle:
        article = session.scalar(
            select(LiyanArticle).where(LiyanArticle.task_version_id == version.id)
        )
        if article is None:
            article = LiyanArticle(
                owner_id=owner_id,
                task_version_id=version.id,
                created_at=datetime.now(UTC),
            )
            session.add(article)
            session.flush()
        return article

    def response_of(
        session: Session,
        task: Task,
        version: TaskVersion,
        article: LiyanArticle | None,
        *,
        now: datetime,
        execution: Execution | None = None,
    ) -> LiyanStateResponse:
        runs = load_runs(session, article.id) if article is not None else None
        latest = execution or (runs.latest if runs is not None else None)
        retry = runs.retry_state(now) if runs is not None else RetryState(True, 2, None)
        active = latest is not None and latest.status in ACTIVE_EXECUTION_STATUSES
        latest_result = (
            session.get(LiyanRunResult, latest.result_id)
            if latest is not None and latest.result_id is not None
            else None
        )
        recoverable_result = latest_result
        if recoverable_result is None and article is not None:
            recoverable_result = session.scalar(
                select(LiyanRunResult)
                .where(LiyanRunResult.article_id == article.id)
                .order_by(LiyanRunResult.created_at.desc())
                .limit(1)
            )
        run_status: LiyanStatus
        if latest_result is not None:
            run_status = "succeeded"
        elif active:
            run_status = "running"
        elif latest is None:
            run_status = "absent"
        elif latest.status == "cancelled":
            run_status = "cancelled"
        else:
            run_status = "failed"
        unavailable = ACTIVE_MESSAGE if active else None
        execution_payload = _safe_execution(latest) if latest is not None else None
        request_payload = _request_response(latest)
        return LiyanStateResponse(
            task_id=str(task.id),
            task_version_id=str(version.id),
            status=run_status,
            execution=execution_payload,
            result=(
                _result_response(session, recoverable_result)
                if recoverable_result is not None
                else None
            ),
            request=request_payload,
            capabilities=LiyanRunCapabilities(
                can_generate=(
                    not active
                    and (latest is None or latest.status != "failed" or retry.allowed)
                ),
                can_cancel=active,
                retry=LiyanRetryState.of(retry),
                unavailable_reason=unavailable,
            ),
        )

    @router.get(
        "/tasks/{task_id}/liyan",
        operation_id="get_task_liyan",
        response_model=LiyanStateResponse,
        tags=["liyan"],
    )
    def get_task_liyan(
        task_id: UUID,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> LiyanStateResponse:
        task, version = owned_current(session, task_id, user.id)
        article = session.scalar(
            select(LiyanArticle).where(LiyanArticle.task_version_id == version.id)
        )
        # The GET is also the durable gate: a direct client cannot infer readiness.
        try:
            complete_context(session, version)
        except HTTPException:
            return LiyanStateResponse(
                task_id=str(task.id),
                task_version_id=str(version.id),
                status="absent",
                execution=None,
                result=None,
                request=None,
                capabilities=LiyanRunCapabilities(
                    can_generate=False,
                    can_cancel=False,
                    retry=LiyanRetryState(allowed=True, remaining=2, allowed_at=None),
                    unavailable_reason=INCOMPLETE_MESSAGE,
                ),
            )
        return response_of(session, task, version, article, now=datetime.now(UTC))

    @router.post(
        "/tasks/{task_id}/liyan-runs",
        operation_id="start_liyan_run",
        response_model=LiyanStateResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["liyan"],
    )
    def start_liyan_run(
        task_id: UUID,
        request: StartLiyanRunRequest,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> LiyanStateResponse:
        task, version = owned_current(session, task_id, user.id)
        context = complete_context(session, version)
        resolved_context, model_instruction = resolve_instruction(
            session, version, request.instruction
        )
        working_copy = request.working_copy.model_dump() if request.working_copy else None
        input_text = liyan_input_text(
            source_report_context=context,
            working_copy=working_copy,
            resolved_instruction_context=resolved_context,
            instruction=model_instruction,
        )
        request_hash = _request_hash(version.id, request.instruction, working_copy)
        replay = session.scalar(
            select(Execution).where(
                Execution.owner_id == user.id,
                Execution.operation == LIYAN_OPERATION,
                Execution.idempotency_key == request.idempotency_key,
            )
        )
        article = article_for(session, version, user.id)
        now = datetime.now(UTC)
        if replay is not None:
            if replay.request_hash != request_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=IDEMPOTENCY_MISMATCH,
                )
            return response_of(
                session, task, version, article, now=now, execution=replay
            )
        runs = load_runs(session, article.id)
        previous = runs.latest
        if previous is not None and previous.status in ACTIVE_EXECUTION_STATUSES:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ACTIVE_MESSAGE)
        retrying = previous is not None and previous.status in {"failed", "stale"}
        if retrying:
            assert previous is not None
            retry = runs.retry_state(now)
            if not retry.allowed:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=RATE_LIMITED_MESSAGE,
                    headers=_retry_after(retry, now),
                )
            if previous.request_hash != request_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=RETRY_INPUT_MISMATCH,
                )
        execution = queue_run(
            session,
            article,
            owner_id=user.id,
            model=settings.liyan_model,
            input_text=input_text,
            instruction=request.instruction,
            working_copy=working_copy,
            input_version=previous.input_version if retrying and previous else (
                previous.input_version + 1 if previous else 1
            ),
            attempt=previous.attempt + 1 if retrying and previous else 1,
            origin="manual" if retrying else "initial",
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
            now=now,
        )
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            replay = session.scalar(
                select(Execution).where(
                    Execution.owner_id == user.id,
                    Execution.operation == LIYAN_OPERATION,
                    Execution.idempotency_key == request.idempotency_key,
                )
            )
            if replay is not None and replay.request_hash == request_hash:
                replay_article = session.scalar(
                    select(LiyanArticle).where(LiyanArticle.task_version_id == version.id)
                )
                assert replay_article is not None
                return response_of(
                    session,
                    task,
                    version,
                    replay_article,
                    now=now,
                    execution=replay,
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=ACTIVE_MESSAGE
            ) from error
        dispatch_or_fail(database, dispatcher, execution.id)
        session.expire_all()
        return response_of(
            session, task, version, article, now=now, execution=execution
        )

    return router


def _request_hash(
    version_id: UUID,
    instruction: InstructionDocument,
    working_copy: dict[str, str] | None,
) -> str:
    value = json.dumps(
        {
            "task_version_id": str(version_id),
            "instruction": instruction.model_dump(mode="json"),
            "working_copy": working_copy,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(value.encode()).hexdigest()


def _safe_execution(execution: Execution) -> ExecutionResponse:
    response = execution_response(execution)
    if execution.status not in {"failed", "stale"}:
        return response
    return response.model_copy(
        update={"error": ExecutionError(code="busy", message=BUSY_MESSAGE)}
    )


def _request_response(execution: Execution | None) -> LiyanRunRequestResponse | None:
    if execution is None:
        return None
    from liyan_server.liyan.runs import InvalidRunSnapshot, LiyanRunSnapshot

    try:
        snapshot = LiyanRunSnapshot.from_json(execution.input_snapshot)
    except InvalidRunSnapshot:
        return None
    return LiyanRunRequestResponse(
        instruction=snapshot.instruction,
        working_copy=(
            WorkingCopyInput.model_validate(snapshot.working_copy)
            if snapshot.working_copy is not None
            else None
        ),
    )


def _result_response(session: Session, result: LiyanRunResult) -> LiyanResultResponse:
    execution = session.get(Execution, result.execution_id)
    instruction = InstructionDocument.from_text(result.instruction)
    if execution is not None:
        from liyan_server.liyan.runs import InvalidRunSnapshot, LiyanRunSnapshot

        with suppress(InvalidRunSnapshot):
            instruction = LiyanRunSnapshot.from_json(execution.input_snapshot).instruction
    return LiyanResultResponse(
        id=str(result.id),
        execution_id=str(result.execution_id),
        task_version_id=str(result.task_version_id),
        title=result.title,
        body_markdown=result.body_markdown,
        instruction=instruction,
        prompt_version=result.prompt_version,
        model=result.model,
        created_at=aware_utc(result.created_at),
    )


def _retry_after(retry: RetryState, now: datetime) -> dict[str, str]:
    if retry.allowed_at is None:
        return {}
    return {"Retry-After": str(max(1, int((retry.allowed_at - now).total_seconds())))}


def _report_item(
    document: dict[str, object], item_id: str
) -> tuple[str, dict[str, object]] | None:
    for section_name, kind in (
        ("facts", "fact"),
        ("viewpoints", "viewpoint"),
        ("logic", "logic"),
        ("intent", "intent"),
    ):
        section = document.get(section_name)
        if not isinstance(section, dict):
            continue
        items = section.get("items")
        if not isinstance(items, list):
            continue
        for candidate in items:
            if isinstance(candidate, dict) and candidate.get("id") == item_id:
                return kind, {
                    key: value
                    for key, value in candidate.items()
                    if key not in {"id", "evidence_ids", "related_ids"}
                }
    return None
