"""Run one Blog attempt outside the API request that confirmed it.

The worker never re-reads the current article: it sends the snapshot locked at
confirmation, which is what keeps a later Revision from silently changing what
was published. It also never retries on its own — a definitive failure is the
user's call (#16), and an unknown outcome is terminal by ADR-0001.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from liyan_server.database import Database, Execution, PublishTask
from liyan_server.execution_states import PublishTaskStatus
from liyan_server.publication.blog import (
    UNKNOWN_OUTCOME_MESSAGE,
    BlogOutcomeUnknown,
    BlogPreviewAccepted,
    BlogPreviewSubmission,
    BlogPreviewSubmitter,
    BlogSubmissionFailure,
)
from liyan_server.publication.runs import publish_task_id


def process_publication_run(
    database_url: str,
    execution_id: UUID,
    submitter: BlogPreviewSubmitter,
    ingest_token: str,
) -> None:
    database = Database(database_url)
    if database.engine is None:
        raise RuntimeError("Database is not configured.")
    try:
        submission = _claim(database, execution_id, ingest_token)
        if submission is None:
            return
        try:
            accepted = submitter.submit(submission)
        except BlogSubmissionFailure as failure:
            _finish(
                database,
                execution_id,
                status="failed",
                failure_code=failure.code,
                failure_message=failure.message,
                internal_error=failure.internal_error,
            )
            return
        except BlogOutcomeUnknown as unknown:
            _unknown(database, execution_id, unknown.internal_error)
            return
        except Exception as error:  # noqa: BLE001 - see below
            # An unexpected fault says nothing about whether Blog wrote the
            # post, and a 发布任务 left pending would poll forever. Treat it the
            # way ADR-0001 treats every inconclusive answer.
            _unknown(database, execution_id, repr(error))
            return
        _succeed(database, execution_id, accepted)
    finally:
        database.dispose()


def _unknown(database: Database, execution_id: UUID, internal_error: str) -> None:
    _finish(
        database,
        execution_id,
        status="outcome_unknown",
        failure_code="outcome_unknown",
        failure_message=UNKNOWN_OUTCOME_MESSAGE,
        internal_error=internal_error,
    )


def _claim(
    database: Database, execution_id: UUID, ingest_token: str
) -> BlogPreviewSubmission | None:
    assert database.engine is not None
    with Session(database.engine) as session:
        execution = session.get(Execution, execution_id)
        if execution is None or execution.status != "queued":
            return None
        publish_task = _publish_task(session, execution)
        if publish_task is None or publish_task.status != "pending":
            return None
        execution.status = "running"
        execution.started_at = datetime.now(UTC)
        session.commit()
        return BlogPreviewSubmission(
            api_base_url=publish_task.target_api_base_url,
            token=ingest_token,
            site_url=publish_task.target_site_url,
            title=publish_task.title,
            body_markdown=publish_task.body_markdown,
            author=publish_task.target_author,
        )


def _publish_task(session: Session, execution: Execution) -> PublishTask | None:
    identifier = publish_task_id(execution.input_snapshot)
    return session.get(PublishTask, identifier) if identifier is not None else None


def _succeed(
    database: Database, execution_id: UUID, accepted: BlogPreviewAccepted
) -> None:
    assert database.engine is not None
    now = datetime.now(UTC)
    with Session(database.engine) as session:
        execution = session.get(Execution, execution_id)
        if execution is None:
            return
        publish_task = _publish_task(session, execution)
        if publish_task is None or publish_task.status != "pending":
            return
        publish_task.status = "succeeded"
        publish_task.preview_path = accepted.preview_path
        publish_task.preview_url = accepted.preview_url(publish_task.target_site_url)
        publish_task.external_slug = accepted.slug
        publish_task.external_version = accepted.version
        publish_task.response_evidence = accepted.response
        publish_task.completed_at = now
        execution.status = "succeeded"
        execution.result_id = publish_task.id
        execution.finished_at = now
        session.commit()


def _finish(
    database: Database,
    execution_id: UUID,
    *,
    status: PublishTaskStatus,
    failure_code: str,
    failure_message: str,
    internal_error: str,
) -> None:
    assert database.engine is not None
    now = datetime.now(UTC)
    with Session(database.engine) as session:
        execution = session.get(Execution, execution_id)
        if execution is None:
            return
        publish_task = _publish_task(session, execution)
        if publish_task is not None and publish_task.status == "pending":
            publish_task.status = status
            publish_task.failure_code = failure_code
            publish_task.failure_message = failure_message
            publish_task.completed_at = now
        execution.status = "failed"
        execution.error_code = failure_code
        execution.error_message = failure_message
        execution.internal_error = internal_error
        execution.finished_at = now
        # Publishing is never retried from inside the server: a blind resend
        # could create a second Blog item.
        execution.retry_allowed_at = None
        session.commit()
