import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from liyan_server.database import Database, Execution, LiyanArticle, aware_utc
from liyan_server.execution_dispatch import ExecutionDispatcher
from liyan_server.execution_states import RunOrigin
from liyan_server.liyan.instruction import InstructionDocument
from liyan_server.liyan.recovery import RetryState, retry_state
from liyan_server.liyan.runs import LIYAN_OPERATION, new_liyan_execution

logger = logging.getLogger(__name__)
DISPATCH_FAILED_MESSAGE = "立言生成未能启动，请重试。"


@dataclass(frozen=True)
class ArticleRuns:
    latest: Execution | None
    manual_run_times: tuple[datetime, ...]

    def retry_state(self, now: datetime) -> RetryState:
        return retry_state(
            now=now,
            manual_run_times=self.manual_run_times,
            earliest_retry_at=(
                aware_utc(self.latest.retry_allowed_at)
                if self.latest is not None and self.latest.retry_allowed_at is not None
                else None
            ),
        )


def load_runs(session: Session, article_id: UUID) -> ArticleRuns:
    runs = list(
        session.scalars(
            select(Execution).where(
                Execution.target_id == article_id,
                Execution.operation == LIYAN_OPERATION,
            )
        ).all()
    )
    return ArticleRuns(
        latest=(
            max(runs, key=lambda run: (run.input_version, run.attempt, run.created_at))
            if runs
            else None
        ),
        manual_run_times=tuple(
            aware_utc(run.created_at) for run in runs if run.origin == "manual"
        ),
    )


def queue_run(
    session: Session,
    article: LiyanArticle,
    *,
    owner_id: UUID,
    model: str,
    input_text: str,
    instruction: InstructionDocument,
    working_copy: dict[str, str] | None,
    input_version: int,
    attempt: int,
    origin: RunOrigin,
    idempotency_key: str | None,
    request_hash: str,
    now: datetime,
) -> Execution:
    execution = new_liyan_execution(
        article,
        owner_id=owner_id,
        model=model,
        input_text=input_text,
        instruction=instruction,
        working_copy=working_copy,
        input_version=input_version,
        attempt=attempt,
        origin=origin,
        created_at=now,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    session.add(execution)
    return execution


def dispatch_or_fail(
    database: Database, dispatcher: ExecutionDispatcher, execution_id: UUID
) -> None:
    try:
        dispatcher.dispatch(execution_id)
    except Exception as error:
        logger.exception("liyan_dispatch_failed", extra={"execution_id": str(execution_id)})
        if database.engine is None:
            return
        from datetime import UTC

        now = datetime.now(UTC)
        with Session(database.engine) as session:
            execution = session.get(Execution, execution_id)
            if execution is None or execution.status != "queued":
                return
            execution.status = "failed"
            execution.error_code = "dispatch_failed"
            execution.error_message = DISPATCH_FAILED_MESSAGE
            execution.internal_error = repr(error)
            execution.finished_at = now
            execution.retry_allowed_at = now
            session.commit()
