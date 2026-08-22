import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePath
from tempfile import SpooledTemporaryFile
from typing import Annotated, BinaryIO, cast
from uuid import UUID, uuid4
from zipfile import BadZipFile, ZipFile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from liyan_server.authentication import CurrentUserDependency
from liyan_server.database import Database, Execution, SourcePreparation, User
from liyan_server.execution_dispatch import ExecutionDispatcher
from liyan_server.execution_states import ACTIVE_EXECUTION_STATUSES, SourcePreparationStatus
from liyan_server.object_storage import ObjectStorage
from liyan_server.settings import Settings
from liyan_server.source_preparation import normalize_source_content, source_warnings
from liyan_server.task_creation_sessions import (
    ensure_session_capacity,
    ensure_unique_identity,
    lock_owner,
    normalized_session_identity,
)
from liyan_server.url_source_api import (
    EditSourceContentRequest,
    ExecutionResponse,
    SourceFailure,
    SourceWarning,
    execution_response,
)

logger = logging.getLogger(__name__)

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SUPPORTED_TYPES = {
    ".pdf": "application/pdf",
    ".docx": DOCX_TYPE,
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}


class FileSourceCapabilities(BaseModel):
    can_retry: bool
    can_replace: bool
    can_cancel: bool


class FileSourceResponse(BaseModel):
    id: str
    client_session_id: str
    client_source_id: str
    filename: str
    content_type: str
    content_hash: str
    size_bytes: int
    input_version: int
    status: SourcePreparationStatus
    title: str | None
    body: str | None
    provenance: str | None
    warnings: list[SourceWarning]
    failure: SourceFailure | None
    active_execution: ExecutionResponse | None
    capabilities: FileSourceCapabilities


@dataclass(frozen=True)
class ValidatedUpload:
    filename: str
    content_type: str
    content_hash: str
    size_bytes: int
    stream: BinaryIO


def _safe_filename(value: str | None) -> str:
    filename = (value or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not filename or len(filename) > 255:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A valid filename is required.",
        )
    return filename


def _validated_content_type(filename: str, declared_type: str | None, stream: BinaryIO) -> str:
    extension = PurePath(filename).suffix.casefold()
    expected = SUPPORTED_TYPES.get(extension)
    if expected is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Upload a PDF, DOCX, TXT, or Markdown document.",
        )
    declared = (declared_type or "").split(";", 1)[0].strip().casefold()
    allowed_declared = {expected}
    if expected == "text/markdown":
        allowed_declared.add("text/plain")
    if declared not in allowed_declared:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The uploaded file does not match its declared type.",
        )
    stream.seek(0)
    header = stream.read(8)
    stream.seek(0)
    matches = False
    if expected == "application/pdf":
        matches = header.startswith(b"%PDF-")
    elif expected == DOCX_TYPE:
        if header.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
            matches = True
        else:
            try:
                with ZipFile(stream) as archive:
                    matches = "[Content_Types].xml" in archive.namelist()
            except BadZipFile:
                # A ZIP-local-header signature with a broken central directory is a
                # damaged DOCX candidate. Persist it so parsing can record a safe,
                # source-specific terminal failure.
                matches = header.startswith(b"PK\x03\x04")
            finally:
                stream.seek(0)
    else:
        try:
            content = stream.read()
            content.decode("utf-8-sig")
            matches = b"\x00" not in content
        except UnicodeDecodeError:
            matches = False
        finally:
            stream.seek(0)
    if not matches:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The uploaded file does not match its declared type.",
        )
    return expected


async def _read_validated_upload(file: UploadFile, *, max_bytes: int) -> ValidatedUpload:
    filename = _safe_filename(file.filename)
    temporary = SpooledTemporaryFile(  # noqa: SIM115 - ownership passes to the caller
        max_size=min(max_bytes, 1024 * 1024),
        mode="w+b",
    )
    digest = hashlib.sha256()
    size_bytes = 0
    try:
        while chunk := await file.read(64 * 1024):
            size_bytes += len(chunk)
            if size_bytes > max_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail=f"The file exceeds the {max_bytes}-byte limit.",
                )
            digest.update(chunk)
            temporary.write(chunk)
        temporary.seek(0)
        stream = cast(BinaryIO, temporary)
        content_type = _validated_content_type(filename, file.content_type, stream)
        return ValidatedUpload(
            filename=filename,
            content_type=content_type,
            content_hash=digest.hexdigest(),
            size_bytes=size_bytes,
            stream=stream,
        )
    except Exception:
        temporary.close()
        raise
    finally:
        await file.close()


def _store_upload(
    storage: ObjectStorage,
    *,
    object_key: str,
    upload: ValidatedUpload,
    source_id: UUID,
) -> None:
    try:
        storage.put(object_key, upload.stream, content_type=upload.content_type)
    except Exception as error:
        logger.exception("file_upload_failed", extra={"source_id": str(source_id)})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The file could not be stored. Try again later.",
        ) from error


def _new_file_execution(source: SourcePreparation, *, attempt: int) -> Execution:
    if (
        not source.object_key
        or not source.filename
        or not source.content_type
        or not source.content_hash
    ):
        raise ValueError("A file source requires a stored immutable input.")
    return Execution(
        owner_id=source.owner_id,
        operation="parse_file",
        target_type="source_preparation",
        target_id=source.id,
        input_version=source.input_version,
        input_identity=source.content_hash,
        input_snapshot={
            "object_key": source.object_key,
            "filename": source.filename,
            "content_type": source.content_type,
            "content_hash": source.content_hash,
            "input_version": source.input_version,
        },
        attempt=attempt,
        status="queued",
        created_at=datetime.now(UTC),
    )


def _response(source: SourcePreparation, execution: Execution | None) -> FileSourceResponse:
    if (
        not source.filename
        or not source.content_type
        or not source.content_hash
        or source.size_bytes is None
    ):
        raise ValueError("File source metadata is incomplete.")
    failure = (
        SourceFailure(code=source.failure_code, message=source.failure_message)
        if source.failure_code and source.failure_message
        else None
    )
    return FileSourceResponse(
        id=str(source.id),
        client_session_id=source.client_session_id,
        client_source_id=source.client_source_id,
        filename=source.filename,
        content_type=source.content_type,
        content_hash=source.content_hash,
        size_bytes=source.size_bytes,
        input_version=source.input_version,
        status=source.status,
        title=source.title,
        body=source.body,
        provenance=source.provenance,
        warnings=[SourceWarning.model_validate(warning) for warning in source.warnings],
        failure=failure,
        active_execution=execution_response(execution) if execution else None,
        capabilities=FileSourceCapabilities(
            can_retry=source.status == "failure",
            can_replace=execution is None or execution.status not in ACTIVE_EXECUTION_STATUSES,
            can_cancel=execution is not None and execution.status in ACTIVE_EXECUTION_STATUSES,
        ),
    )


def file_source_router(
    settings: Settings,
    database: Database,
    current_user: CurrentUserDependency,
    dispatcher: ExecutionDispatcher,
    storage: ObjectStorage,
) -> APIRouter:
    router = APIRouter()

    def owned_source(
        session: Session,
        source_id: UUID,
        owner_id: UUID,
        *,
        for_update: bool = False,
    ) -> SourcePreparation:
        statement = select(SourcePreparation).where(
            SourcePreparation.id == source_id,
            SourcePreparation.owner_id == owner_id,
            SourcePreparation.kind == "file",
            SourcePreparation.confirmed_task_id.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        source = session.scalar(statement)
        if source is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found.")
        return source

    def dispatch(execution_id: UUID) -> None:
        try:
            dispatcher.dispatch(execution_id)
        except Exception as error:
            logger.exception("execution_dispatch_failed", extra={"execution_id": str(execution_id)})
            if database.engine is None:
                return
            now = datetime.now(UTC)
            with Session(database.engine) as recovery:
                execution = recovery.get(Execution, execution_id)
                if execution is None or execution.status != "queued":
                    return
                execution.status = "failed"
                execution.error_code = "dispatch_failed"
                execution.error_message = (
                    "Parsing could not be started. Retry it or replace this source."
                )
                execution.internal_error = repr(error)
                execution.finished_at = now
                source = recovery.get(SourcePreparation, execution.target_id)
                if source is not None and source.active_execution_id == execution.id:
                    source.status = "failure"
                    source.failure_code = execution.error_code
                    source.failure_message = execution.error_message
                    source.updated_at = now
                recovery.commit()

    @router.post(
        "/task-creation/file-sources",
        operation_id="create_file_source",
        response_model=FileSourceResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["task creation"],
    )
    async def create_file_source(
        client_session_id: Annotated[str, Form()],
        client_source_id: Annotated[str, Form()],
        file: Annotated[UploadFile, File()],
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> FileSourceResponse:
        session_identity = normalized_session_identity(client_session_id)
        source_identity = client_source_id.strip()
        if not source_identity:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Client source identity is required.",
            )
        upload = await _read_validated_upload(file, max_bytes=settings.file_max_bytes)
        try:
            ensure_session_capacity(
                session,
                owner_id=user.id,
                client_session_id=session_identity,
            )
            ensure_unique_identity(
                session,
                owner_id=user.id,
                client_session_id=session_identity,
                kind="file",
                identity_column=SourcePreparation.content_hash,
                identity=upload.content_hash,
            )
            source_id = uuid4()
            object_key = (
                f"users/{user.id}/source-preparations/{source_id}/v1/"
                f"{upload.content_hash}-{upload.filename}"
            )
            _store_upload(
                storage,
                object_key=object_key,
                upload=upload,
                source_id=source_id,
            )
        finally:
            upload.stream.close()

        now = datetime.now(UTC)
        source = SourcePreparation(
            id=source_id,
            owner_id=user.id,
            client_session_id=session_identity,
            client_source_id=source_identity,
            kind="file",
            filename=upload.filename,
            content_type=upload.content_type,
            object_key=object_key,
            content_hash=upload.content_hash,
            size_bytes=upload.size_bytes,
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
            storage.delete(object_key)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This browser source identity is already in use.",
            ) from error
        execution = _new_file_execution(source, attempt=1)
        session.add(execution)
        session.flush()
        source.active_execution_id = execution.id
        session.commit()
        dispatch(execution.id)
        session.refresh(source)
        session.refresh(execution)
        return _response(source, execution)

    @router.get(
        "/task-creation/file-sources/{source_id}",
        operation_id="get_file_source",
        response_model=FileSourceResponse,
        tags=["task creation"],
    )
    def get_file_source(
        source_id: UUID,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> FileSourceResponse:
        source = owned_source(session, source_id, user.id)
        execution = (
            session.get(Execution, source.active_execution_id)
            if source.active_execution_id
            else None
        )
        return _response(source, execution)

    @router.put(
        "/task-creation/file-sources/{source_id}",
        operation_id="replace_file_source",
        response_model=FileSourceResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["task creation"],
    )
    async def replace_file_source(
        source_id: UUID,
        file: Annotated[UploadFile, File()],
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> FileSourceResponse:
        lock_owner(session, user.id)
        source = owned_source(session, source_id, user.id, for_update=True)
        current = (
            session.get(Execution, source.active_execution_id)
            if source.active_execution_id
            else None
        )
        if current is not None and current.status in ACTIVE_EXECUTION_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cancel active parsing before replacing this source.",
            )
        upload = await _read_validated_upload(file, max_bytes=settings.file_max_bytes)
        try:
            ensure_unique_identity(
                session,
                owner_id=user.id,
                client_session_id=source.client_session_id,
                kind="file",
                identity_column=SourcePreparation.content_hash,
                identity=upload.content_hash,
                excluding_source_id=source.id,
            )
            next_version = source.input_version + 1
            object_key = (
                f"users/{user.id}/source-preparations/{source.id}/v{next_version}/"
                f"{upload.content_hash}-{upload.filename}"
            )
            _store_upload(
                storage,
                object_key=object_key,
                upload=upload,
                source_id=source.id,
            )
        finally:
            upload.stream.close()

        now = datetime.now(UTC)
        source.filename = upload.filename
        source.content_type = upload.content_type
        source.object_key = object_key
        source.content_hash = upload.content_hash
        source.size_bytes = upload.size_bytes
        source.input_version = next_version
        source.status = "processing"
        source.title = None
        source.body = None
        source.provenance = None
        source.warnings = []
        source.failure_code = None
        source.failure_message = None
        source.accepted_result_id = None
        source.updated_at = now
        execution = _new_file_execution(source, attempt=1)
        session.add(execution)
        session.flush()
        source.active_execution_id = execution.id
        session.commit()
        dispatch(execution.id)
        session.refresh(source)
        session.refresh(execution)
        return _response(source, execution)

    @router.post(
        "/task-creation/file-sources/{source_id}/retry",
        operation_id="retry_file_source",
        response_model=FileSourceResponse,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["task creation"],
    )
    def retry_file_source(
        source_id: UUID,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> FileSourceResponse:
        source = owned_source(session, source_id, user.id, for_update=True)
        current = (
            session.get(Execution, source.active_execution_id)
            if source.active_execution_id
            else None
        )
        if source.status != "failure" or current is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This source is not eligible for retry.",
            )
        execution = _new_file_execution(source, attempt=current.attempt + 1)
        session.add(execution)
        session.flush()
        source.status = "processing"
        source.failure_code = None
        source.failure_message = None
        source.active_execution_id = execution.id
        source.updated_at = datetime.now(UTC)
        session.commit()
        dispatch(execution.id)
        session.refresh(source)
        session.refresh(execution)
        return _response(source, execution)

    @router.patch(
        "/task-creation/file-sources/{source_id}/content",
        operation_id="edit_file_source_content",
        response_model=FileSourceResponse,
        tags=["task creation"],
    )
    def edit_file_source_content(
        source_id: UUID,
        request: EditSourceContentRequest,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(database.session)],
    ) -> FileSourceResponse:
        source = owned_source(session, source_id, user.id, for_update=True)
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
        source.title = normalized.title
        source.body = normalized.body
        source.provenance = normalized.provenance
        source.input_version += 1
        source.warnings = source_warnings(
            body=normalized.body,
            provenance=normalized.provenance,
            short_source_characters=settings.short_source_characters,
        )
        source.status = "warning" if source.warnings else "ready"
        source.updated_at = datetime.now(UTC)
        execution = (
            session.get(Execution, source.active_execution_id)
            if source.active_execution_id
            else None
        )
        session.commit()
        return _response(source, execution)

    return router
