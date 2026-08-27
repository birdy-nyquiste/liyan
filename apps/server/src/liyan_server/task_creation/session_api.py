from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from liyan_server.authentication import CurrentUserDependency
from liyan_server.credit_limits import refuse_when_short
from liyan_server.credits import charge_capture
from liyan_server.database import Database, Execution, SourcePreparation, User
from liyan_server.execution_states import ACTIVE_EXECUTION_STATUSES, SourcePreparationStatus
from liyan_server.object_storage import ObjectStorage
from liyan_server.rate_card import CAPTURE_CREDITS
from liyan_server.settings import Settings
from liyan_server.source_preparation import normalize_source_content, source_warnings
from liyan_server.task_creation.contracts import (
    ExecutionResponse,
    SourceFailure,
    SourceWarning,
    execution_response,
)
from liyan_server.task_creation.sessions import (
    MAX_SESSION_SOURCES,
    ensure_session_capacity,
    ensure_unique_identity,
    lock_owner,
    normalized_body_hash,
    normalized_session_identity,
)


class CreatePastedSourceRequest(BaseModel):
    client_session_id: str
    client_source_id: str
    title: str
    body: str
    provenance: str | None = None


class EditPastedSourceRequest(BaseModel):
    title: str
    body: str
    provenance: str | None = None


class SessionSourceCapabilities(BaseModel):
    can_retry: bool
    can_replace: bool
    can_edit: bool
    can_delete: bool
    can_cancel: bool


class SessionSourceResponse(BaseModel):
    id: str
    client_source_id: str
    kind: Literal["pasted", "url", "file"]
    input_version: int
    status: SourcePreparationStatus
    title: str | None
    body: str | None
    provenance: str | None
    warnings: list[SourceWarning]
    failure: SourceFailure | None
    active_execution: ExecutionResponse | None
    capabilities: SessionSourceCapabilities


class TaskCreationSessionResponse(BaseModel):
    client_session_id: str
    source_count: int
    max_sources: Literal[3] = 3
    can_add: bool
    can_confirm: bool
    confirmation_disabled_reason: str | None
    sources: list[SessionSourceResponse]


def _active_execution(session: Session, source: SourcePreparation) -> Execution | None:
    return (
        session.get(Execution, source.active_execution_id) if source.active_execution_id else None
    )


def session_source_response(
    session: Session,
    source: SourcePreparation,
) -> SessionSourceResponse:
    execution = _active_execution(session, source)
    active = execution is not None and execution.status in ACTIVE_EXECUTION_STATUSES
    terminal = not active
    failure = (
        SourceFailure(code=source.failure_code, message=source.failure_message)
        if source.failure_code and source.failure_message
        else None
    )
    return SessionSourceResponse(
        id=str(source.id),
        client_source_id=source.client_source_id,
        kind=source.kind,  # type: ignore[arg-type]
        input_version=source.input_version,
        status=source.status,
        title=source.title,
        body=source.body,
        provenance=source.provenance,
        warnings=[SourceWarning.model_validate(warning) for warning in source.warnings],
        failure=failure,
        active_execution=execution_response(execution) if execution else None,
        capabilities=SessionSourceCapabilities(
            can_retry=source.status == "failure" and source.kind in {"url", "file"},
            can_replace=terminal,
            can_edit=terminal and source.status in {"ready", "warning"},
            can_delete=terminal,
            can_cancel=active,
        ),
    )


def task_creation_session_router(
    settings: Settings,
    database: Database,
    current_user: CurrentUserDependency,
    storage: ObjectStorage,
) -> APIRouter:
    router = APIRouter()

    def owned_source(
        session: Session,
        *,
        source_id: UUID,
        owner_id: UUID,
        kind: str | None = None,
        for_update: bool = False,
    ) -> SourcePreparation:
        statement = select(SourcePreparation).where(
            SourcePreparation.id == source_id,
            SourcePreparation.owner_id == owner_id,
            SourcePreparation.confirmed_task_id.is_(None),
        )
        if kind is not None:
            statement = statement.where(SourcePreparation.kind == kind)
        if for_update:
            statement = statement.with_for_update()
        source = session.scalar(statement)
        if source is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found.")
        return source

    def session_response(
        session: Session,
        *,
        owner_id: UUID,
        client_session_id: str,
    ) -> TaskCreationSessionResponse:
        sources = session.scalars(
            select(SourcePreparation)
            .where(
                SourcePreparation.owner_id == owner_id,
                SourcePreparation.client_session_id == client_session_id,
                SourcePreparation.confirmed_task_id.is_(None),
            )
            .order_by(SourcePreparation.created_at, SourcePreparation.id)
        ).all()
        all_ready = bool(sources) and all(
            source.status in {"ready", "warning"} for source in sources
        )
        if not sources:
            reason = "Add at least one source before confirmation."
        elif not all_ready:
            reason = "Wait for every source to be ready before confirmation."
        else:
            reason = None
        return TaskCreationSessionResponse(
            client_session_id=client_session_id,
            source_count=len(sources),
            can_add=len(sources) < MAX_SESSION_SOURCES,
            can_confirm=all_ready,
            confirmation_disabled_reason=reason,
            sources=[session_source_response(session, source) for source in sources],
        )

    @router.post(
        "/task-creation/pasted-sources",
        operation_id="create_pasted_source",
        response_model=SessionSourceResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["task creation"],
    )
    def create_pasted_source(
        request: CreatePastedSourceRequest,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> SessionSourceResponse:
        client_session_id = normalized_session_identity(request.client_session_id)
        client_source_id = request.client_source_id.strip()
        if not client_source_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A client source identity is required.",
            )
        normalized = normalize_source_content(
            title=request.title,
            body=request.body,
            provenance=request.provenance,
        )
        content_hash = normalized_body_hash(normalized.body)
        # A pasted 来源 queues no Execution and reaches no browser, so nothing
        # gates it but the fee itself: every 来源 costs the same to carry once
        # it is in a 任务版本, whichever way it arrived.
        refuse_when_short(session, user.id, needed=CAPTURE_CREDITS)
        ensure_session_capacity(
            session,
            owner_id=user.id,
            client_session_id=client_session_id,
        )
        ensure_unique_identity(
            session,
            owner_id=user.id,
            client_session_id=client_session_id,
            kind="pasted",
            identity_column=SourcePreparation.content_hash,
            identity=content_hash,
        )
        warnings = source_warnings(
            body=normalized.body,
            provenance=normalized.provenance,
            short_source_characters=settings.short_source_characters,
        )
        now = datetime.now(UTC)
        source = SourcePreparation(
            owner_id=user.id,
            client_session_id=client_session_id,
            client_source_id=client_source_id,
            kind="pasted",
            content_hash=content_hash,
            input_version=1,
            status="warning" if warnings else "ready",
            title=normalized.title,
            body=normalized.body,
            provenance=normalized.provenance,
            warnings=warnings,
            created_at=now,
            updated_at=now,
        )
        session.add(source)
        try:
            session.flush()
            charge_capture(session, user.id, preparation_id=source.id, credits=CAPTURE_CREDITS)
            session.commit()
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This browser source identity is already in use.",
            ) from error
        return session_source_response(session, source)

    @router.patch(
        "/task-creation/pasted-sources/{source_id}",
        operation_id="edit_pasted_source",
        response_model=SessionSourceResponse,
        tags=["task creation"],
    )
    def edit_pasted_source(
        source_id: UUID,
        request: EditPastedSourceRequest,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> SessionSourceResponse:
        lock_owner(session, user.id)
        source = owned_source(
            session,
            source_id=source_id,
            owner_id=user.id,
            kind="pasted",
            for_update=True,
        )
        normalized = normalize_source_content(
            title=request.title,
            body=request.body,
            provenance=request.provenance,
        )
        content_hash = normalized_body_hash(normalized.body)
        ensure_unique_identity(
            session,
            owner_id=user.id,
            client_session_id=source.client_session_id,
            kind="pasted",
            identity_column=SourcePreparation.content_hash,
            identity=content_hash,
            excluding_source_id=source.id,
        )
        warnings = source_warnings(
            body=normalized.body,
            provenance=normalized.provenance,
            short_source_characters=settings.short_source_characters,
        )
        source.title = normalized.title
        source.body = normalized.body
        source.provenance = normalized.provenance
        source.content_hash = content_hash
        source.input_version += 1
        source.warnings = warnings
        source.status = "warning" if warnings else "ready"
        source.updated_at = datetime.now(UTC)
        session.commit()
        return session_source_response(session, source)

    @router.get(
        "/task-creation/sessions/{client_session_id}",
        operation_id="get_task_creation_session",
        response_model=TaskCreationSessionResponse,
        tags=["task creation"],
    )
    def get_task_creation_session(
        client_session_id: str,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> TaskCreationSessionResponse:
        return session_response(
            session,
            owner_id=user.id,
            client_session_id=normalized_session_identity(client_session_id),
        )

    @router.delete(
        "/task-creation/sources/{source_id}",
        operation_id="delete_task_creation_source",
        status_code=status.HTTP_204_NO_CONTENT,
        tags=["task creation"],
    )
    def delete_task_creation_source(
        source_id: UUID,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> Response:
        source = owned_source(
            session,
            source_id=source_id,
            owner_id=user.id,
            for_update=True,
        )
        execution = _active_execution(session, source)
        if execution is not None and execution.status in ACTIVE_EXECUTION_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cancel active processing before deleting this source.",
            )
        if source.object_key:
            storage.delete(source.object_key)
        source.active_execution_id = None
        source.accepted_result_id = None
        session.flush()
        session.delete(source)
        session.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
