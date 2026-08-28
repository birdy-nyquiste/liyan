import hashlib
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy.orm import Session

from liyan_server.database import Database, Execution, FileParseResult, SourcePreparation
from liyan_server.execution_states import surrendered
from liyan_server.file_parsing import FileParseFailure, FileParseLimits, parse_file
from liyan_server.metering import record_execution_cost
from liyan_server.object_storage import ObjectStorage
from liyan_server.observability import log_execution_failed
from liyan_server.source_preparation import source_warnings


def _cancelled_message() -> str:
    return "Parsing was cancelled. Retry it or replace this source."


def _mark_failed(database: Database, execution_id: UUID, failure: FileParseFailure) -> None:
    if database.engine is None:
        raise RuntimeError("Database is not configured.")
    now = datetime.now(UTC)
    with Session(database.engine) as session:
        execution = session.get(Execution, execution_id)
        if execution is None:
            return
        if surrendered(execution.status):
            # The stalled sweep already ended this run and told the 来源 so.
            return
        source = session.get(SourcePreparation, execution.target_id)
        cancelled = execution.cancellation_requested_at is not None or execution.status in {
            "cancel_requested",
            "cancelled",
        }
        execution.status = "cancelled" if cancelled else "failed"
        execution.error_code = failure.code
        execution.error_message = failure.message
        execution.internal_error = failure.internal_error
        execution.finished_at = now
        log_execution_failed(
            execution_id=execution.id,
            operation=execution.operation,
            attempt=execution.attempt,
            error_code=execution.error_code,
        )
        if (
            source is not None
            and source.active_execution_id == execution.id
            and source.input_version == execution.input_version
        ):
            source.status = "failure"
            source.failure_code = "cancelled" if cancelled else failure.code
            source.failure_message = _cancelled_message() if cancelled else failure.message
            source.updated_at = now
        _record_cost(session, execution, source)
        session.commit()


def process_file_parse(
    database_url: str,
    execution_id: UUID,
    storage: ObjectStorage,
    *,
    limits: FileParseLimits,
    short_source_characters: int,
) -> None:
    database = Database(database_url)
    if database.engine is None:
        raise RuntimeError("Database is not configured.")
    try:
        with Session(database.engine) as session:
            execution = session.get(Execution, execution_id)
            if execution is None or execution.status != "queued":
                return
            execution.status = "running"
            execution.started_at = datetime.now(UTC)
            object_key = execution.input_snapshot.get("object_key")
            filename = execution.input_snapshot.get("filename")
            content_type = execution.input_snapshot.get("content_type")
            if not all(isinstance(value, str) for value in (object_key, filename, content_type)):
                raise RuntimeError("File parse Execution has an invalid input snapshot.")
            session.commit()

        try:
            with storage.open(cast(str, object_key)) as stream:
                parsed = parse_file(
                    stream,
                    filename=cast(str, filename),
                    content_type=cast(str, content_type),
                    limits=limits,
                )
        except FileParseFailure as failure:
            _mark_failed(database, execution_id, failure)
            return
        except Exception as error:
            _mark_failed(
                database,
                execution_id,
                FileParseFailure(
                    "parse_failed",
                    "The document could not be processed. Retry it or replace this source.",
                    repr(error),
                ),
            )
            return

        now = datetime.now(UTC)
        with Session(database.engine) as session:
            execution = session.get(Execution, execution_id)
            if execution is None:
                return
            if surrendered(execution.status):
                # Writing now would put a body into a 来源 whose run the system
                # already reported as failed, and which the user may have
                # retried since.
                return
            result = FileParseResult(
                execution_id=execution.id,
                input_identity=execution.input_identity,
                title=parsed.title,
                body=parsed.body,
                provenance=cast(str, filename),
                document_metadata=parsed.metadata,
                content_hash=hashlib.sha256(parsed.body.encode()).hexdigest(),
                created_at=now,
            )
            session.add(result)
            session.flush()
            execution.result_id = result.id
            execution.finished_at = now
            source = session.get(SourcePreparation, execution.target_id)
            if (
                execution.cancellation_requested_at is not None
                or execution.status == "cancel_requested"
            ):
                execution.status = "cancelled"
                if (
                    source is not None
                    and source.active_execution_id == execution.id
                    and source.input_version == execution.input_version
                ):
                    source.status = "failure"
                    source.failure_code = "cancelled"
                    source.failure_message = _cancelled_message()
                    source.updated_at = now
            elif (
                source is None
                or source.active_execution_id != execution.id
                or source.input_version != execution.input_version
            ):
                execution.status = "stale"
            else:
                warnings = source_warnings(
                    body=result.body,
                    provenance=result.provenance,
                    short_source_characters=short_source_characters,
                )
                execution.status = "succeeded"
                source.status = "warning" if warnings else "ready"
                source.title = result.title
                source.body = result.body
                source.provenance = result.provenance
                source.warnings = warnings
                source.failure_code = None
                source.failure_message = None
                source.accepted_result_id = result.id
                source.updated_at = now
            _record_cost(session, execution, source)
            session.commit()
    finally:
        database.dispose()

def _record_cost(session: Session, execution: Execution, source: SourcePreparation | None) -> None:
    """What capturing this 来源 cost, and what the flat fee would take for it.

    Chargeable only when the 来源 is one the user ended up with: a capture that
    failed or was superseded left them nothing to pay for. The bytes are the
    upload's, because R2 keeps them for as long as the 来源 lives.
    """
    record_execution_cost(
        session,
        execution,
        chargeable=execution.status == "succeeded",
        stored_bytes=source.size_bytes if source else None,
    )
