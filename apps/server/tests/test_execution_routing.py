"""Which worker an Execution reaches.

The queue hands the worker nothing but an Execution id, so this branch is the
only thing connecting a queued 发布任务 to the code that submits it. Nothing here
touches a provider: each handler is replaced, and the test asserts only that the
right one was chosen for the operation stored on the row.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from database_support import migrated_database
from sqlalchemy.orm import Session

from liyan_server import celery_worker
from liyan_server.database import Database, Execution, User
from liyan_server.execution_dispatch import EXECUTION_QUEUE, CeleryExecutionDispatcher
from liyan_server.settings import Settings


def _queued(database_url: str, operation: str) -> UUID:
    database = Database(database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        user = User(auth_subject="subject-1", email="writer@example.com")
        session.add(user)
        session.flush()
        execution = Execution(
            owner_id=user.id,
            operation=operation,
            target_type="whatever",
            target_id=uuid4(),
            input_version=1,
            input_identity="identity",
            input_snapshot={},
            attempt=1,
            status="queued",
            created_at=datetime.now(UTC),
        )
        session.add(execution)
        session.commit()
        execution_id = execution.id
    database.dispose()
    return execution_id


@pytest.mark.parametrize(
    ("operation", "handler"),
    [
        ("publish_preview", "publish_preview_execution"),
        ("analyze_source", "analyze_source_execution"),
        ("generate_article", "generate_article_execution"),
        ("fetch_url", "fetch_url_execution"),
    ],
)
def test_each_operation_reaches_the_worker_that_performs_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    handler: str,
) -> None:
    database_url = migrated_database(tmp_path)
    execution_id = _queued(database_url, operation)
    monkeypatch.setattr(celery_worker, "settings", Settings(database_url=database_url))
    reached: list[str] = []
    for name in (
        "publish_preview_execution",
        "analyze_source_execution",
        "generate_article_execution",
        "fetch_url_execution",
    ):
        monkeypatch.setattr(
            celery_worker,
            name,
            lambda _id, name=name: reached.append(name),
        )
    monkeypatch.setattr(
        celery_worker, "process_file_parse", lambda *a, **k: reached.append("parse_file")
    )

    celery_worker.process_execution(str(execution_id))

    assert reached == [handler]


def test_an_unknown_operation_is_ignored_rather_than_crashing_the_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = migrated_database(tmp_path)
    execution_id = _queued(database_url, "something_new")
    monkeypatch.setattr(celery_worker, "settings", Settings(database_url=database_url))

    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("No handler should run for an unknown operation.")

    for name in ("publish_preview_execution", "analyze_source_execution"):
        monkeypatch.setattr(celery_worker, name, refuse)

    celery_worker.process_execution(str(execution_id))


def test_the_worker_listens_where_the_api_sends() -> None:
    """The quietest possible failure, and the only thing that catches it.

    A producer that sends to a queue the consumer does not listen on breaks
    nothing visibly: the API accepts the work and answers 202, the queue fills,
    the worker sits idle reporting itself healthy, and every task shows as
    processing forever. Beat keeps running, because its own tasks go to the
    default queue — which makes the worker look alive while it consumes nothing.
    """
    assert celery_worker.celery_app.conf.task_default_queue == EXECUTION_QUEUE


def test_a_dispatched_execution_is_addressed_to_that_queue() -> None:
    sent: dict[str, object] = {}

    class RecordingCelery:
        def send_task(self, name: str, *, args: list[str], queue: str) -> None:
            sent.update({"name": name, "args": args, "queue": queue})

    dispatcher = CeleryExecutionDispatcher.__new__(CeleryExecutionDispatcher)
    dispatcher._celery = RecordingCelery()
    execution_id = uuid4()

    dispatcher.dispatch(execution_id)

    assert sent["queue"] == EXECUTION_QUEUE
    assert sent["args"] == [str(execution_id)]
