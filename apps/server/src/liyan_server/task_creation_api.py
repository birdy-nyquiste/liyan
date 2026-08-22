import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from liyan_server.authentication import CurrentUserDependency
from liyan_server.database import (
    Database,
    Source,
    SourceRevision,
    Task,
    TaskVersion,
    TaskVersionSource,
    User,
)
from liyan_server.settings import Settings
from liyan_server.source_preparation import normalize_source_content, source_warnings
from liyan_server.task_api import TaskSummary, task_summary


class SourceInput(BaseModel):
    title: str
    body: str
    provenance: str | None = None


class PreparedSource(BaseModel):
    title: str
    body: str
    provenance: str | None


class PreparationWarning(BaseModel):
    code: Literal["short_body", "missing_provenance"]
    message: str


class PrepareSourceResponse(BaseModel):
    source: PreparedSource
    warnings: list[PreparationWarning]
    can_confirm: Literal[True] = True


class ConfirmTaskRequest(BaseModel):
    idempotency_key: str
    source: SourceInput


class SourceRevisionResponse(BaseModel):
    id: str
    title: str
    body: str
    provenance: str | None


class ConfirmTaskResponse(BaseModel):
    task: TaskSummary
    source_revision: SourceRevisionResponse


def normalize_source(source: SourceInput) -> PreparedSource:
    normalized = normalize_source_content(
        title=source.title,
        body=source.body,
        provenance=source.provenance,
    )
    return PreparedSource(
        title=normalized.title,
        body=normalized.body,
        provenance=normalized.provenance,
    )


def _request_hash(source: PreparedSource) -> str:
    canonical = json.dumps(
        source.model_dump(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _revision_response(session: Session, task: Task) -> SourceRevisionResponse:
    revision = session.scalar(
        select(SourceRevision)
        .join(
            TaskVersionSource,
            TaskVersionSource.source_revision_id == SourceRevision.id,
        )
        .where(
            TaskVersionSource.task_version_id == task.current_version_id,
            TaskVersionSource.position == 0,
        )
    )
    if revision is None:
        raise ValueError("A formal task must have an initial source revision.")
    return SourceRevisionResponse(
        id=str(revision.id),
        title=revision.title,
        body=revision.body,
        provenance=revision.provenance,
    )


def task_creation_router(
    settings: Settings,
    database: Database,
    current_user: CurrentUserDependency,
) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/task-creation/prepare",
        operation_id="prepare_task_source",
        response_model=PrepareSourceResponse,
        tags=["task creation"],
    )
    def prepare_task_source(
        source: SourceInput,
        _: Annotated[User, Depends(current_user)],
    ) -> PrepareSourceResponse:
        prepared = normalize_source(source)
        warnings = [
            PreparationWarning.model_validate(warning)
            for warning in source_warnings(
                body=prepared.body,
                provenance=prepared.provenance,
                short_source_characters=settings.short_source_characters,
            )
        ]
        return PrepareSourceResponse(source=prepared, warnings=warnings)

    @router.post(
        "/task-creation/confirm",
        operation_id="confirm_task_creation",
        response_model=ConfirmTaskResponse,
        tags=["task creation"],
    )
    def confirm_task_creation(
        request: ConfirmTaskRequest,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> ConfirmTaskResponse:
        idempotency_key = request.idempotency_key.strip()
        if not idempotency_key:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="An idempotency key is required.",
            )
        prepared = normalize_source(request.source)
        request_hash = _request_hash(prepared)

        locked_user = session.scalar(select(User).where(User.id == user.id).with_for_update())
        if locked_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication is required.",
            )
        existing = session.scalar(
            select(Task).where(
                Task.owner_id == locked_user.id,
                Task.creation_idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.creation_request_hash != request_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This creation request was already used with different content.",
                )
            return ConfirmTaskResponse(
                task=task_summary(session, existing),
                source_revision=_revision_response(session, existing),
            )

        now = datetime.now(UTC)
        task = Task(
            owner_id=locked_user.id,
            number=locked_user.next_task_number,
            display_name=prepared.title,
            creation_idempotency_key=idempotency_key,
            creation_request_hash=request_hash,
            created_at=now,
        )
        session.add(task)
        session.flush()
        version = TaskVersion(task_id=task.id, number=1, created_at=now)
        source = Source(task_id=task.id)
        session.add_all([version, source])
        session.flush()
        revision = SourceRevision(
            source_id=source.id,
            title=prepared.title,
            body=prepared.body,
            provenance=prepared.provenance,
            content_hash=request_hash,
            created_at=now,
        )
        session.add(revision)
        session.flush()
        session.add(
            TaskVersionSource(
                task_version_id=version.id,
                source_revision_id=revision.id,
                position=0,
            )
        )
        task.current_version_id = version.id
        locked_user.next_task_number += 1
        session.commit()
        return ConfirmTaskResponse(
            task=task_summary(session, task),
            source_revision=SourceRevisionResponse(
                id=str(revision.id),
                title=revision.title,
                body=revision.body,
                provenance=revision.provenance,
            ),
        )

    return router
