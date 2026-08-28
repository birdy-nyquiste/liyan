"""Which worker an Execution reaches.

The queue hands the worker nothing but an Execution id, so this branch is the
only thing connecting a queued 发布任务 to the code that submits it. Nothing here
touches a provider: each handler is replaced, and the test asserts only that the
right one was chosen for the operation stored on the row.
"""

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from database_support import migrated_database
from sqlalchemy.orm import Session

from liyan_server import celery_worker
from liyan_server.database import Database, Execution, User
from liyan_server.execution_dispatch import (
    PROVIDER_QUEUE,
    QUEUE_BY_OPERATION,
    SOURCE_QUEUE,
    CeleryExecutionDispatcher,
    queue_for,
)
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


def test_unrouted_work_falls_to_the_heavy_queue_rather_than_celerys_own() -> None:
    """The quietest possible failure, and the only thing that catches it.

    A producer that sends to a queue the consumer does not listen on breaks
    nothing visibly: the API accepts the work and answers 202, the queue fills,
    the worker sits idle reporting itself healthy, and every task shows as
    processing forever.
    """
    assert celery_worker.celery_app.conf.task_default_queue == SOURCE_QUEUE


def test_every_operation_is_routed_and_none_is_routed_by_accident() -> None:
    """The split is by what work costs a machine, not by what it means.

    Chromium and the parsers need a process to themselves on a 512MB instance.
    A 知言 run, a 立言 generation, and a Blog submission are all a socket someone
    else is slow on. Putting them on one queue made a memory budget throttle a
    network wait.
    """
    assert QUEUE_BY_OPERATION == {
        "fetch_url": SOURCE_QUEUE,
        "parse_file": SOURCE_QUEUE,
        "analyze_source": PROVIDER_QUEUE,
        "generate_article": PROVIDER_QUEUE,
        "publish_preview": PROVIDER_QUEUE,
    }
    # Every operation `process_execution` can branch on is routed. One that is
    # not would silently take the default and run beside Chromium forever, so
    # the branch itself is read rather than a second list of it being kept.
    assert set(QUEUE_BY_OPERATION) == _operations_the_worker_handles()
    # An unknown operation goes to the heavy queue, which is the conservative
    # answer rather than an unbounded number of them sharing an interpreter.
    assert queue_for("something_new") == SOURCE_QUEUE


@pytest.mark.parametrize(
    ("operation", "queue"),
    sorted((operation, queue) for operation, queue in QUEUE_BY_OPERATION.items()),
)
def test_a_dispatched_execution_is_addressed_to_its_own_queue(
    operation: str, queue: str
) -> None:
    sent: dict[str, object] = {}

    class RecordingCelery:
        def send_task(self, name: str, *, args: list[str], queue: str) -> None:
            sent.update({"name": name, "args": args, "queue": queue})

    dispatcher = CeleryExecutionDispatcher.__new__(CeleryExecutionDispatcher)
    dispatcher._celery = RecordingCelery()
    execution_id = uuid4()

    dispatcher.dispatch(execution_id, operation)

    assert sent["queue"] == queue
    assert sent["args"] == [str(execution_id)]


def test_beat_sends_its_sweeps_where_a_provider_worker_will_take_them() -> None:
    """Sweeps are database and R2 work. The heavy queue's single slot is far too
    scarce to spend on one, and a sweep queued behind a 10MB PDF does not run."""
    schedule = celery_worker.celery_app.conf.beat_schedule

    assert schedule["clean-expired-data"]["options"]["queue"] == PROVIDER_QUEUE
    assert schedule["recover-stalled-executions"]["options"]["queue"] == PROVIDER_QUEUE


def test_beat_gives_every_queue_something_to_do() -> None:
    """A heartbeat is written on the way into a run, so an idle queue writes
    none — and after the split `source-processing` genuinely idles for hours.
    Without a ping a perfectly healthy worker reports `silent`, and the signal
    becomes a function of demand rather than of health."""
    schedule = celery_worker.celery_app.conf.beat_schedule
    pinged = {
        entry["options"]["queue"]
        for entry in schedule.values()
        if entry["task"] == "liyan.ping"
    }

    assert pinged == {SOURCE_QUEUE, PROVIDER_QUEUE}


def _operations_the_worker_handles() -> set[str]:
    """The operations `process_execution` actually branches on.

    Read out of the source rather than restated here. A second hand-kept list
    would be one more thing to forget, and forgetting it is precisely the bug
    this asserts against — an operation with a handler and no route runs on
    whichever queue the default happens to name.
    """
    source = Path(celery_worker.__file__).read_text(encoding="utf-8")
    body = source[source.index("def process_execution("):]
    return set(re.findall(r'operation == "([a-z_]+)"', body))


def test_a_shared_engine_survives_the_task_that_borrowed_it(tmp_path: Path) -> None:
    """Every worker task builds a `Database` and disposes it in a `finally`.

    At one task at a time that is one pool at a time and nobody notices. On a
    thread pool it is N pools of up to fifteen connections against one small
    Postgres — intermittent connection exhaustion that reads as a database
    problem rather than a pool-sizing one. So the provider worker shares one
    engine, and a per-task dispose must not close the pool the other threads
    are mid-query on.
    """
    from liyan_server.database import forget_shared_engines, share_engine

    database_url = migrated_database(tmp_path)
    try:
        share_engine(database_url, pool_size=6)
        borrowed = Database(database_url)
        again = Database(database_url)
        assert borrowed.engine is again.engine, "one engine for the whole process"

        borrowed.dispose()

        assert again.is_available(), "the other thread's connections are still good"
    finally:
        forget_shared_engines()


def test_a_process_that_shares_nothing_still_gets_its_own_engine(tmp_path: Path) -> None:
    """Opt-in. The API is served by one engine already and tests build a
    database per temporary directory; neither starts sharing because a worker
    needed to."""
    database_url = migrated_database(tmp_path)

    first = Database(database_url)
    second = Database(database_url)

    assert first.engine is not second.engine
    first.dispose()
    assert second.is_available()
