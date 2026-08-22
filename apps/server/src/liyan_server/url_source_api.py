import hashlib
import ipaddress
import logging
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import SplitResult, urlsplit, urlunsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from liyan_server.authentication import CurrentUserDependency
from liyan_server.database import Database, Execution, SourcePreparation, User
from liyan_server.execution_dispatch import ExecutionDispatcher
from liyan_server.execution_states import (
    ACTIVE_EXECUTION_STATUSES,
    ExecutionStatus,
    SourcePreparationStatus,
)
from liyan_server.settings import Settings
from liyan_server.source_preparation import normalize_source_content, source_warnings

logger = logging.getLogger(__name__)


class CreateUrlSourceRequest(BaseModel):
    client_session_id: str
    client_source_id: str
    url: str


class EditSourceContentRequest(BaseModel):
    title: str
    body: str
    provenance: str | None = None


class ReplaceUrlSourceRequest(BaseModel):
    url: str


class SourceWarning(BaseModel):
    code: str
    message: str


class SourceFailure(BaseModel):
    code: str
    message: str


class ExecutionError(BaseModel):
    code: str
    message: str


class ExecutionResponse(BaseModel):
    id: str
    operation: Literal["fetch_url", "parse_file"]
    status: ExecutionStatus
    attempt: int
    input_version: int
    trace_id: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    cancellation_requested_at: datetime | None
    result_id: str | None
    error: ExecutionError | None


class UrlSourceCapabilities(BaseModel):
    can_retry: bool
    can_replace: bool
    can_cancel: bool


class UrlSourceResponse(BaseModel):
    id: str
    client_session_id: str
    client_source_id: str
    input_url: str
    normalized_url: str
    input_version: int
    status: SourcePreparationStatus
    title: str | None
    body: str | None
    provenance: str | None
    warnings: list[SourceWarning]
    failure: SourceFailure | None
    active_execution: ExecutionResponse | None
    capabilities: UrlSourceCapabilities


def normalize_public_url(value: str) -> tuple[str, str]:
    input_url = value.strip()
    try:
        parsed = urlsplit(input_url)
        port = parsed.port
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Enter a supported public HTTP or HTTPS article URL.",
        ) from error
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Enter a supported public HTTP or HTTPS article URL.",
        )
    hostname = parsed.hostname.casefold().encode("idna").decode("ascii")
    try:
        literal_address = ipaddress.ip_address(hostname)
    except ValueError:
        literal_address = None
    if (
        hostname == "localhost"
        or hostname.endswith(".localhost")
        or (literal_address is not None and not literal_address.is_global)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Enter a supported public HTTP or HTTPS article URL.",
        )
    default_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    netloc = hostname if port is None or default_port else f"{hostname}:{port}"
    normalized = urlunsplit(
        SplitResult(
            scheme=scheme,
            netloc=netloc,
            path=parsed.path or "/",
            query=parsed.query,
            fragment="",
        )
    )
    return input_url, normalized


def new_url_fetch_execution(
    source: SourcePreparation,
    *,
    attempt: int,
    created_at: datetime,
) -> Execution:
    if source.normalized_url is None:
        raise ValueError("A URL source requires a normalized URL.")
    input_identity = hashlib.sha256(f"url:{source.normalized_url}".encode()).hexdigest()
    return Execution(
        owner_id=source.owner_id,
        operation="fetch_url",
        target_type="source_preparation",
        target_id=source.id,
        input_version=source.input_version,
        input_identity=input_identity,
        input_snapshot={
            "normalized_url": source.normalized_url,
            "input_version": source.input_version,
        },
        attempt=attempt,
        status="queued",
        created_at=created_at,
    )


def execution_response(execution: Execution) -> ExecutionResponse:
    error = (
        ExecutionError(code=execution.error_code, message=execution.error_message)
        if execution.error_code and execution.error_message
        else None
    )
    return ExecutionResponse(
        id=str(execution.id),
        operation=execution.operation,  # type: ignore[arg-type]
        status=execution.status,
        attempt=execution.attempt,
        input_version=execution.input_version,
        trace_id=str(execution.trace_id),
        created_at=execution.created_at,
        started_at=execution.started_at,
        finished_at=execution.finished_at,
        cancellation_requested_at=execution.cancellation_requested_at,
        result_id=str(execution.result_id) if execution.result_id else None,
        error=error,
    )


def url_source_response(
    source: SourcePreparation, execution: Execution | None
) -> UrlSourceResponse:
    if source.input_url is None or source.normalized_url is None:
        raise ValueError("URL source metadata is incomplete.")
    failure = (
        SourceFailure(code=source.failure_code, message=source.failure_message)
        if source.failure_code and source.failure_message
        else None
    )
    return UrlSourceResponse(
        id=str(source.id),
        client_session_id=source.client_session_id,
        client_source_id=source.client_source_id,
        input_url=source.input_url,
        normalized_url=source.normalized_url,
        input_version=source.input_version,
        status=source.status,
        title=source.title,
        body=source.body,
        provenance=source.provenance,
        warnings=[SourceWarning.model_validate(warning) for warning in source.warnings],
        failure=failure,
        active_execution=execution_response(execution) if execution else None,
        capabilities=UrlSourceCapabilities(
            can_retry=source.status == "failure",
            can_replace=execution is None or execution.status not in ACTIVE_EXECUTION_STATUSES,
            can_cancel=execution is not None and execution.status in ACTIVE_EXECUTION_STATUSES,
        ),
    )


def url_source_router(
    settings: Settings,
    database: Database,
    current_user: CurrentUserDependency,
    dispatcher: ExecutionDispatcher,
) -> APIRouter:
    router = APIRouter()

    def dispatch(execution_id: UUID) -> None:
        try:
            dispatcher.dispatch(execution_id)
        except Exception as error:
            logger.exception(
                "execution_dispatch_failed",
                extra={"execution_id": str(execution_id)},
            )
            if database.engine is None:
                return
            now = datetime.now(UTC)
            with Session(database.engine) as recovery_session:
                execution = recovery_session.get(Execution, execution_id)
                if execution is None or execution.status != "queued":
                    return
                execution.status = "failed"
                execution.error_code = "dispatch_failed"
                execution.error_message = (
                    "Fetching could not be started. Retry it or replace this source."
                )
                execution.internal_error = repr(error)
                execution.finished_at = now
                source = recovery_session.get(SourcePreparation, execution.target_id)
                if source is not None and source.active_execution_id == execution.id:
                    source.status = "failure"
                    source.failure_code = execution.error_code
                    source.failure_message = execution.error_message
                    source.updated_at = now
                recovery_session.commit()

    def owned_source(
        session: Session,
        *,
        source_id: UUID,
        owner_id: UUID,
        for_update: bool = False,
    ) -> SourcePreparation:
        statement = select(SourcePreparation).where(
            SourcePreparation.id == source_id,
            SourcePreparation.owner_id == owner_id,
        )
        if for_update:
            statement = statement.with_for_update()
        source = session.scalar(statement)
        if source is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found.")
        return source

    @router.post(
        "/task-creation/url-sources",
        operation_id="create_url_source",
        response_model=UrlSourceResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["task creation"],
    )
    def create_url_source(
        request: CreateUrlSourceRequest,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> UrlSourceResponse:
        client_session_id = request.client_session_id.strip()
        client_source_id = request.client_source_id.strip()
        if not client_session_id or not client_source_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Client source identity is required.",
            )
        input_url, normalized_url = normalize_public_url(request.url)
        now = datetime.now(UTC)
        source = SourcePreparation(
            owner_id=user.id,
            client_session_id=client_session_id,
            client_source_id=client_source_id,
            kind="url",
            input_url=input_url,
            normalized_url=normalized_url,
            input_version=1,
            status="processing",
            warnings=[],
            created_at=now,
            updated_at=now,
        )
        session.add(source)
        try:
            session.flush()
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This browser source identity is already in use.",
            ) from error
        execution = new_url_fetch_execution(source, attempt=1, created_at=now)
        session.add(execution)
        session.flush()
        source.active_execution_id = execution.id
        session.commit()
        dispatch(execution.id)
        session.refresh(source)
        session.refresh(execution)
        return url_source_response(source, execution)

    @router.get(
        "/task-creation/url-sources/{source_id}",
        operation_id="get_url_source",
        response_model=UrlSourceResponse,
        tags=["task creation"],
    )
    def get_url_source(
        source_id: UUID,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> UrlSourceResponse:
        source = owned_source(session, source_id=source_id, owner_id=user.id)
        execution = (
            session.get(Execution, source.active_execution_id)
            if source.active_execution_id
            else None
        )
        return url_source_response(source, execution)

    @router.post(
        "/task-creation/url-sources/{source_id}/retry",
        operation_id="retry_url_source",
        response_model=UrlSourceResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["task creation"],
    )
    def retry_url_source(
        source_id: UUID,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> UrlSourceResponse:
        source = owned_source(session, source_id=source_id, owner_id=user.id, for_update=True)
        current_execution = (
            session.get(Execution, source.active_execution_id)
            if source.active_execution_id
            else None
        )
        if source.status != "failure" or current_execution is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This source is not eligible for retry.",
            )
        now = datetime.now(UTC)
        execution = new_url_fetch_execution(
            source,
            attempt=current_execution.attempt + 1,
            created_at=now,
        )
        session.add(execution)
        session.flush()
        source.status = "processing"
        source.failure_code = None
        source.failure_message = None
        source.active_execution_id = execution.id
        source.updated_at = now
        session.commit()
        dispatch(execution.id)
        session.refresh(source)
        session.refresh(execution)
        return url_source_response(source, execution)

    @router.patch(
        "/task-creation/url-sources/{source_id}/content",
        operation_id="edit_url_source_content",
        response_model=UrlSourceResponse,
        tags=["task creation"],
    )
    def edit_url_source_content(
        source_id: UUID,
        request: EditSourceContentRequest,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> UrlSourceResponse:
        source = owned_source(session, source_id=source_id, owner_id=user.id, for_update=True)
        if source.status not in {"ready", "warning"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only prepared source content can be edited.",
            )
        normalized = normalize_source_content(
            title=request.title,
            body=request.body,
            provenance=request.provenance,
        )
        warnings = source_warnings(
            body=normalized.body,
            provenance=normalized.provenance,
            short_source_characters=settings.short_source_characters,
        )
        source.title = normalized.title
        source.body = normalized.body
        source.provenance = normalized.provenance
        source.warnings = warnings
        source.status = "warning" if warnings else "ready"
        source.updated_at = datetime.now(UTC)
        execution = (
            session.get(Execution, source.active_execution_id)
            if source.active_execution_id
            else None
        )
        session.commit()
        return url_source_response(source, execution)

    @router.put(
        "/task-creation/url-sources/{source_id}",
        operation_id="replace_url_source",
        response_model=UrlSourceResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["task creation"],
    )
    def replace_url_source(
        source_id: UUID,
        request: ReplaceUrlSourceRequest,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> UrlSourceResponse:
        source = owned_source(session, source_id=source_id, owner_id=user.id, for_update=True)
        input_url, normalized_url = normalize_public_url(request.url)
        now = datetime.now(UTC)
        current_execution = (
            session.get(Execution, source.active_execution_id)
            if source.active_execution_id
            else None
        )
        if current_execution is not None and current_execution.status in ACTIVE_EXECUTION_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cancel the active fetch before replacing this source.",
            )

        source.input_url = input_url
        source.normalized_url = normalized_url
        source.input_version += 1
        source.status = "processing"
        source.title = None
        source.body = None
        source.provenance = None
        source.warnings = []
        source.failure_code = None
        source.failure_message = None
        source.accepted_result_id = None
        source.updated_at = now
        execution = new_url_fetch_execution(source, attempt=1, created_at=now)
        session.add(execution)
        session.flush()
        source.active_execution_id = execution.id
        session.commit()
        dispatch(execution.id)
        session.refresh(source)
        session.refresh(execution)
        return url_source_response(source, execution)

    @router.get(
        "/executions/{execution_id}",
        operation_id="get_execution",
        response_model=ExecutionResponse,
        tags=["executions"],
    )
    def get_execution(
        execution_id: UUID,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> ExecutionResponse:
        execution = session.scalar(
            select(Execution).where(
                Execution.id == execution_id,
                Execution.owner_id == user.id,
            )
        )
        if execution is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Execution not found.",
            )
        return execution_response(execution)

    @router.post(
        "/executions/{execution_id}/cancel",
        operation_id="cancel_execution",
        response_model=ExecutionResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["executions"],
    )
    def cancel_execution(
        execution_id: UUID,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> ExecutionResponse:
        execution = session.scalar(
            select(Execution)
            .where(Execution.id == execution_id, Execution.owner_id == user.id)
            .with_for_update()
        )
        if execution is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Execution not found.",
            )
        if execution.status not in ACTIVE_EXECUTION_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This Execution is already terminal.",
            )
        now = datetime.now(UTC)
        execution.cancellation_requested_at = execution.cancellation_requested_at or now
        source = session.get(SourcePreparation, execution.target_id)
        cancelled_message = (
            "Parsing was cancelled. Retry it or replace this source."
            if execution.operation == "parse_file"
            else "Fetching was cancelled. Retry it or replace this source."
        )
        if execution.status == "queued":
            execution.status = "cancelled"
            execution.finished_at = now
            if (
                source is not None
                and source.active_execution_id == execution.id
                and source.input_version == execution.input_version
            ):
                source.status = "failure"
                source.failure_code = "cancelled"
                source.failure_message = cancelled_message
                source.updated_at = now
        else:
            execution.status = "cancel_requested"
        session.commit()
        return execution_response(execution)

    return router
