"""Starting one Blog attempt, including when the queue itself refuses it.

A 发布任务 that cannot be queued has definitively sent nothing, so it must end
as a failure the user can see rather than waiting on work that will never run.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from liyan_server.database import Database, Execution, PublishTask
from liyan_server.execution_dispatch import ExecutionDispatcher

logger = logging.getLogger(__name__)
DISPATCH_FAILED_CODE = "dispatch_failed"
DISPATCH_FAILED_MESSAGE = "发布未能启动，请稍后重试。"


def dispatch_publication(
    database: Database,
    dispatcher: ExecutionDispatcher,
    execution_id: UUID,
    publish_task_id: UUID,
) -> None:
    try:
        dispatcher.dispatch(execution_id)
    except Exception as error:
        logger.exception("publication_dispatch_failed", extra={"execution_id": str(execution_id)})
        if database.engine is None:
            return
        now = datetime.now(UTC)
        with Session(database.engine) as session:
            execution = session.get(Execution, execution_id)
            publish_task = session.get(PublishTask, publish_task_id)
            if execution is None or execution.status != "queued":
                return
            execution.status = "failed"
            execution.error_code = DISPATCH_FAILED_CODE
            execution.error_message = DISPATCH_FAILED_MESSAGE
            execution.internal_error = repr(error)
            execution.finished_at = now
            execution.retry_allowed_at = None
            if publish_task is not None and publish_task.status == "pending":
                publish_task.status = "failed"
                publish_task.failure_code = DISPATCH_FAILED_CODE
                publish_task.failure_message = DISPATCH_FAILED_MESSAGE
                publish_task.completed_at = now
            session.commit()
