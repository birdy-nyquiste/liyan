import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy.orm import Session

from liyan_server.database import Database, Execution, SourcePreparation, UrlFetchResult
from liyan_server.execution_states import surrendered
from liyan_server.observability import log_execution_failed
from liyan_server.source_preparation import source_warnings
from liyan_server.source_text import without_nul, without_nul_in_mapping


@dataclass(frozen=True)
class UrlExtraction:
    title: str | None
    body: str
    metadata: dict[str, object]


class UrlFetcher(Protocol):
    def fetch(self, url: str) -> UrlExtraction: ...


class UrlFetchFailure(Exception):
    def __init__(self, code: str, message: str, internal_error: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.internal_error = internal_error


def _normalize_title(title: str | None, normalized_url: str) -> tuple[str, list[dict[str, str]]]:
    normalized_title = " ".join(without_nul(title).split()) if title else ""
    if normalized_title:
        return normalized_title, []
    fallback = urlsplit(normalized_url).hostname or normalized_url
    return fallback, [
        {
            "code": "missing_title",
            "message": "No page title was found; review the suggested title.",
        }
    ]


def _normalize_body(body: str) -> str:
    normalized = without_nul(body).replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise UrlFetchFailure(
            "empty_body",
            "No usable article text was found. Replace this source or try another URL.",
        )
    return normalized


def _mark_failed(database: Database, execution_id: UUID, failure: UrlFetchFailure) -> None:
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
        if execution.cancellation_requested_at is not None or execution.status in {
            "cancel_requested",
            "cancelled",
        }:
            execution.status = "cancelled"
            execution.error_code = failure.code
            execution.error_message = failure.message
            execution.internal_error = failure.internal_error
            execution.finished_at = now
            if (
                source is not None
                and source.active_execution_id == execution.id
                and source.input_version == execution.input_version
            ):
                source.status = "failure"
                source.failure_code = "cancelled"
                source.failure_message = "Fetching was cancelled. Retry it or replace this source."
                source.updated_at = now
            session.commit()
            return
        execution.status = "failed"
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
            source.failure_code = failure.code
            source.failure_message = failure.message
            source.updated_at = now
        session.commit()


def process_url_fetch(
    database_url: str,
    execution_id: UUID,
    fetcher: UrlFetcher,
    *,
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
            snapshot_url = execution.input_snapshot.get("normalized_url")
            if not isinstance(snapshot_url, str):
                raise RuntimeError("URL fetch Execution has an invalid input snapshot.")
            session.commit()

        try:
            extraction = fetcher.fetch(snapshot_url)
            normalized_body = _normalize_body(extraction.body)
            normalized_title, warnings = _normalize_title(extraction.title, snapshot_url)
            warnings.extend(
                source_warnings(
                    body=normalized_body,
                    provenance=snapshot_url,
                    short_source_characters=short_source_characters,
                )
            )
        except UrlFetchFailure as failure:
            _mark_failed(database, execution_id, failure)
            return
        except Exception as error:
            _mark_failed(
                database,
                execution_id,
                UrlFetchFailure(
                    "fetch_failed",
                    "The article could not be fetched. Retry it or replace this source.",
                    internal_error=repr(error),
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
            result = UrlFetchResult(
                execution_id=execution.id,
                input_identity=execution.input_identity,
                title=normalized_title,
                body=normalized_body,
                provenance=snapshot_url,
                page_metadata=without_nul_in_mapping(extraction.metadata),
                content_hash=hashlib.sha256(normalized_body.encode()).hexdigest(),
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
                    source.failure_message = (
                        "Fetching was cancelled. Retry it or replace this source."
                    )
                    source.updated_at = now
            elif (
                source is None
                or source.active_execution_id != execution.id
                or source.input_version != execution.input_version
            ):
                execution.status = "stale"
            else:
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
            session.commit()
    finally:
        database.dispose()
