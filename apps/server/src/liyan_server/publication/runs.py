"""The Execution identity of one Blog attempt.

A 发布任务 holds the immutable snapshot; the Execution holds the attempt. The
queue message therefore carries nothing but identity, and the worker reads what
to send from PostgreSQL rather than from the message it was handed.
"""

import hashlib
from datetime import datetime
from uuid import UUID

from liyan_server.database import Execution, PublishTask
from liyan_server.execution_states import RunOrigin

PUBLISH_OPERATION = "publish_preview"
PUBLISH_TARGET_TYPE = "publish_task"


def new_publish_execution(
    publish_task: PublishTask,
    *,
    created_at: datetime,
    attempt: int = 1,
    origin: RunOrigin = "initial",
    idempotency_key: str | None = None,
) -> Execution:
    """One attempt at the 发布任务's snapshot, whichever attempt it is.

    Every attempt reads the same snapshot, so a retry cannot send anything the
    first attempt did not: `input_identity` is derived from the Revision and the
    locked content hash, and stays equal across attempts by construction.
    """
    identity = ":".join(
        (
            "publish",
            str(publish_task.id),
            str(publish_task.revision_id),
            publish_task.target_key,
            publish_task.content_hash,
        )
    )
    return Execution(
        owner_id=publish_task.owner_id,
        operation=PUBLISH_OPERATION,
        target_type=PUBLISH_TARGET_TYPE,
        target_id=publish_task.id,
        input_version=1,
        input_identity=hashlib.sha256(identity.encode()).hexdigest(),
        input_snapshot=publish_snapshot(publish_task),
        attempt=attempt,
        origin=origin,
        status="queued",
        created_at=created_at,
        idempotency_key=idempotency_key,
        request_hash=publish_task.content_hash,
    )


def publish_snapshot(publish_task: PublishTask) -> dict[str, object]:
    return {
        "publish_task_id": str(publish_task.id),
        "revision_id": str(publish_task.revision_id),
        "target_key": publish_task.target_key,
        "content_hash": publish_task.content_hash,
    }


def publish_task_id(snapshot: dict[str, object]) -> UUID | None:
    value = snapshot.get("publish_task_id")
    return UUID(value) if isinstance(value, str) else None
