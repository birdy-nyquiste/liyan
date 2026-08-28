import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from liyan_server.authentication import CurrentUserDependency
from liyan_server.credit_limits import hold_zhiyan_batch
from liyan_server.database import (
    Database,
    Source,
    SourcePreparation,
    SourceRevision,
    Task,
    TaskVersion,
    TaskVersionSource,
    User,
)
from liyan_server.execution_dispatch import ExecutionDispatcher
from liyan_server.execution_limits import refuse_when_at_capacity
from liyan_server.settings import Settings
from liyan_server.source_preparation import normalize_source_content, source_warnings
from liyan_server.task_api import TaskSummary, task_summary
from liyan_server.zhiyan.orchestration import queue_initial_runs


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
    source: SourceInput | None = None
    client_session_id: str | None = None
    source_ids: list[UUID] = Field(default_factory=list)
    accepted_warning_versions: dict[UUID, int] = Field(default_factory=dict)


class SourceRevisionResponse(BaseModel):
    id: str
    title: str
    body: str
    provenance: str | None


class ConfirmTaskResponse(BaseModel):
    task: TaskSummary
    source_revision: SourceRevisionResponse
    source_revisions: list[SourceRevisionResponse]


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


def _request_hash(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _revision_responses(session: Session, task: Task) -> list[SourceRevisionResponse]:
    revisions = session.scalars(
        select(SourceRevision)
        .join(
            TaskVersionSource,
            TaskVersionSource.source_revision_id == SourceRevision.id,
        )
        .where(
            TaskVersionSource.task_version_id == task.current_version_id,
        )
        .order_by(TaskVersionSource.position)
    ).all()
    if not revisions:
        raise ValueError("A formal task must have an initial source revision.")
    return [
        SourceRevisionResponse(
            id=str(revision.id),
            title=revision.title,
            body=revision.body,
            provenance=revision.provenance,
        )
        for revision in revisions
    ]


def task_creation_router(
    settings: Settings,
    database: Database,
    current_user: CurrentUserDependency,
    dispatcher: ExecutionDispatcher,
) -> APIRouter:
    router = APIRouter()

    def start_zhiyan(owner_id: UUID, revision_ids: list[UUID]) -> None:
        queue_initial_runs(
            database,
            dispatcher,
            source_revision_ids=revision_ids,
            owner_id=owner_id,
            model=settings.zhiyan_model,
        )

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
        if request.source is not None:
            prepared_sources = [normalize_source(request.source)]
            request_identity: object = [prepared_sources[0].model_dump()]
        else:
            client_session_id = (request.client_session_id or "").strip()
            if not client_session_id or not 1 <= len(request.source_ids) <= 3:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Confirmation requires one to three session sources.",
                )
            if len(set(request.source_ids)) != len(request.source_ids):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Confirmation source identities must be unique.",
                )
            request_identity = {
                "client_session_id": client_session_id,
                "source_ids": [str(source_id) for source_id in request.source_ids],
            }
            prepared_sources = []
        request_hash = _request_hash(request_identity)

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
                Task.deleted_at.is_(None),
            )
        )
        if existing is not None:
            if existing.creation_request_hash != request_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This creation request was already used with different content.",
                )
            existing_revisions = _revision_responses(session, existing)
            session.commit()  # Release the number lock before queueing outside this transaction.
            start_zhiyan(
                locked_user.id,
                [UUID(revision.id) for revision in existing_revisions],
            )
            return ConfirmTaskResponse(
                task=task_summary(session, existing),
                source_revision=existing_revisions[0],
                source_revisions=existing_revisions,
            )

        refuse_when_at_capacity(session, settings, owner_id=user.id)

        if request.source is None:
            session_sources = session.scalars(
                select(SourcePreparation).where(
                    SourcePreparation.owner_id == locked_user.id,
                    SourcePreparation.client_session_id == client_session_id,
                    SourcePreparation.confirmed_task_id.is_(None),
                )
                .with_for_update()
            ).all()
            by_id = {source.id: source for source in session_sources}
            if set(by_id) != set(request.source_ids):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Confirmation must include every retained session source exactly once.",
                )
            ordered_sources = [by_id[source_id] for source_id in request.source_ids]
            if any(source.status not in {"ready", "warning"} for source in ordered_sources):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Every source must be ready before confirmation.",
                )
            warnings_accepted = all(
                request.accepted_warning_versions.get(source.id) == source.input_version
                for source in ordered_sources
                if source.warnings
            )
            if not warnings_accepted:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Accept every source warning before confirmation.",
                )
            prepared_sources = [
                PreparedSource(
                    title=source.title or "",
                    body=source.body or "",
                    provenance=source.provenance,
                )
                for source in ordered_sources
            ]

        now = datetime.now(UTC)
        task = Task(
            owner_id=locked_user.id,
            number=locked_user.next_task_number,
            display_name=prepared_sources[0].title,
            creation_idempotency_key=idempotency_key,
            creation_request_hash=request_hash,
            created_at=now,
            last_activity_at=now,
        )
        session.add(task)
        session.flush()
        version = TaskVersion(task_id=task.id, number=1, created_at=now)
        session.add(version)
        session.flush()
        created_revisions: list[SourceRevision] = []
        for position, prepared in enumerate(prepared_sources):
            source = Source(task_id=task.id)
            session.add(source)
            session.flush()
            content_hash = _request_hash(prepared.model_dump())
            revision = SourceRevision(
                source_id=source.id,
                source_preparation_id=(
                    ordered_sources[position].id if request.source is None else None
                ),
                title=prepared.title,
                body=prepared.body,
                provenance=prepared.provenance,
                content_hash=content_hash,
                created_at=now,
            )
            session.add(revision)
            session.flush()
            session.add(
                TaskVersionSource(
                    task_version_id=version.id,
                    source_revision_id=revision.id,
                    position=position,
                )
            )
            created_revisions.append(revision)
        task.current_version_id = version.id
        if request.source is None:
            for session_source in ordered_sources:
                session_source.confirmed_task_id = task.id
        locked_user.next_task_number += 1
        hold_zhiyan_batch(session, user.id, created_revisions, model=settings.zhiyan_model)
        session.commit()
        revision_responses = [
            SourceRevisionResponse(
                id=str(revision.id),
                title=revision.title,
                body=revision.body,
                provenance=revision.provenance,
            )
            for revision in created_revisions
        ]
        start_zhiyan(locked_user.id, [revision.id for revision in created_revisions])
        return ConfirmTaskResponse(
            task=task_summary(session, task),
            source_revision=revision_responses[0],
            source_revisions=revision_responses,
        )

    return router
