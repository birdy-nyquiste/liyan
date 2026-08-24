"""What an operator can see, and what the system does when a worker dies.

Readiness answers "can this deployment do its job right now", so it has to name
each dependency separately: a queue nobody can reach and a database nobody can
reach are different outages with different fixes. And an Execution whose worker
died looks exactly like one still working, forever, unless something notices.
"""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from cleanup_support import MemoryObjectStorage, cleanup_client, later
from database_support import QueueSaying, migrated_database
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from zhiyan_support import confirm_sources, unavailable, zhiyan_client

from liyan_server.app import create_app
from liyan_server.database import Database, Execution, User, ZhiyanReport
from liyan_server.settings import Settings
from liyan_server.stalled import (
    NEVER_STARTED_CODE,
    STALLED_CODE,
    StalledPolicy,
    recover_stalled_executions,
)
from liyan_server.worker_health import record_heartbeat, silent_workers


def _client(tmp_path: Path, *, reachable: bool = True) -> tuple[TestClient, str]:
    database_url = migrated_database(tmp_path)
    client = TestClient(
        create_app(
            Settings(database_url=database_url, allowed_emails="writer@example.com"),
            execution_dispatcher=QueueSaying(reachable),
            object_storage=MemoryObjectStorage(),
        )
    )
    return client, database_url


def test_readiness_names_the_queue_separately_from_the_database(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    ready = client.get("/health/ready")

    assert ready.status_code == 200, ready.text
    assert ready.json()["checks"]["queue"] == "available"


def test_an_unreachable_queue_makes_the_deployment_not_ready(tmp_path: Path) -> None:
    """Unlike object storage, nothing works without the queue.

    Every 来源, 知言 run, 立言 generation, and Blog submission is queued work, so
    a deployment that cannot reach the broker cannot do its job at all — which
    is what readiness is asked to report.
    """
    client, _ = _client(tmp_path, reachable=False)

    ready = client.get("/health/ready")

    assert ready.status_code == 503, ready.text
    body = ready.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["queue"] == "unavailable"
    assert body["checks"]["database"] == "available"


def test_a_worker_that_has_never_run_is_reported_as_unknown(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)

    ready = client.get("/health/ready")

    assert ready.json()["checks"]["worker"] == "unknown"


def test_a_worker_that_just_ran_is_reported_as_beating(tmp_path: Path) -> None:
    client, database_url = _client(tmp_path)
    record_heartbeat(database_url, "celery-worker-1")

    ready = client.get("/health/ready")

    assert ready.json()["checks"]["worker"] == "beating"


def test_a_worker_that_stopped_reporting_stops_being_called_healthy(
    tmp_path: Path,
) -> None:
    """A silent worker is the failure that leaves every task pending forever."""
    client, database_url = _client(tmp_path)
    record_heartbeat(
        database_url, "celery-worker-1", at=datetime.now(UTC) - timedelta(hours=2)
    )

    ready = client.get("/health/ready")

    assert ready.json()["checks"]["worker"] == "silent"


def _running_execution(database_url: str, *, started_at: datetime) -> UUID:
    """One Execution left mid-flight, as a killed worker would leave it."""
    database = Database(database_url)
    assert database.engine is not None
    execution_id = uuid4()
    with Session(database.engine) as session:
        owner = User(email="writer@example.com", auth_subject="supabase-user-1")
        session.add(owner)
        session.flush()
        session.add(
            Execution(
                id=execution_id,
                owner_id=owner.id,
                operation="analyze_source",
                target_type="source_revision",
                target_id=uuid4(),
                input_version=1,
                input_identity="identity",
                input_snapshot={},
                attempt=1,
                origin="initial",
                status="running",
                created_at=started_at,
                started_at=started_at,
            )
        )
        session.commit()
    database.dispose()
    return execution_id


def _execution(database_url: str, execution_id: UUID) -> Any:
    database = Database(database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        found = session.get(Execution, execution_id)
        assert found is not None
        state = (found.status, found.error_code, found.retry_allowed_at)
    database.dispose()
    return state


def test_an_execution_whose_worker_died_stops_being_pending_forever(
    tmp_path: Path,
) -> None:
    database_url = migrated_database(tmp_path)
    execution_id = _running_execution(database_url, started_at=datetime.now(UTC))

    report = recover_stalled_executions(
        database_url, policy=StalledPolicy(), now=later(hours=2)
    )

    assert report.stalled_executions == 1
    status, code, _ = _execution(database_url, execution_id)
    assert status == "failed"
    assert code == STALLED_CODE


def test_work_still_inside_its_timeout_is_left_running(tmp_path: Path) -> None:
    database_url = migrated_database(tmp_path)
    execution_id = _running_execution(database_url, started_at=datetime.now(UTC))

    report = recover_stalled_executions(
        database_url, policy=StalledPolicy(), now=later(minutes=5)
    )

    assert report.stalled_executions == 0
    assert _execution(database_url, execution_id)[0] == "running"


def test_a_recovered_execution_is_never_reopened_by_a_late_answer(
    tmp_path: Path,
) -> None:
    """The worker may still be alive and about to answer.

    Marking it failed is a guess about a process nobody can see, so the guess
    must not be undone by whatever arrives afterwards. The workers already
    refuse to write to an Execution they no longer own; this pins that the
    recovery leaves it in exactly the state that refusal keys on.
    """
    database_url = migrated_database(tmp_path)
    execution_id = _running_execution(database_url, started_at=datetime.now(UTC))

    recover_stalled_executions(database_url, policy=StalledPolicy(), now=later(hours=2))
    again = recover_stalled_executions(
        database_url, policy=StalledPolicy(), now=later(hours=3)
    )

    assert again.stalled_executions == 0
    status, _, _ = _execution(database_url, execution_id)
    assert status == "failed"


def test_the_queue_message_carries_identity_and_never_the_work(tmp_path: Path) -> None:
    """A queue is not a place to put a 来源 body or an article.

    Redis is another store with another retention and another set of eyes on it,
    so the message says which Execution to run and the worker reads the rest
    from PostgreSQL under the ownership checks that live there.
    """
    client, headers, dispatcher, storage, database_url = cleanup_client(tmp_path)
    created = client.post(
        "/task-creation/url-sources",
        headers=headers,
        json={
            "client_session_id": "session-1",
            "client_source_id": "source-1",
            "url": "https://autonomy.work/four-day-week-pilot",
        },
    )
    assert created.status_code == 201, created.text

    assert dispatcher.execution_ids
    for queued in dispatcher.execution_ids:
        assert isinstance(queued, UUID)


def test_a_stored_snapshot_holds_identifiers_rather_than_business_content(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, storage, database_url = cleanup_client(tmp_path)
    client.post(
        "/task-creation/url-sources",
        headers=headers,
        json={
            "client_session_id": "session-1",
            "client_source_id": "source-1",
            "url": "https://autonomy.work/four-day-week-pilot",
        },
    )

    database = Database(database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        snapshots = [row.input_snapshot for row in session.scalars(select(Execution))]
    database.dispose()

    assert snapshots
    for snapshot in snapshots:
        for key in ("body", "body_markdown", "report", "instruction", "token"):
            assert key not in snapshot


def test_a_late_provider_answer_cannot_undo_a_recovered_execution(
    tmp_path: Path,
) -> None:
    """The race the sweep creates, and the reason it must be safe.

    Presuming a run dead is a guess about a process nobody can watch, and the
    guess is sometimes wrong: the worker was slow, not gone. When it finally
    answers, that answer is about a run the system has already given up on, and
    accepting it would let a 知言报告 appear under a failed Execution — after
    the user was told it failed and may have started another.
    """
    client, headers, dispatcher = zhiyan_client(tmp_path)
    confirm_sources(client, headers, ["四天工作制已经没有争议"])
    swept: list[int] = []

    original = dispatcher.provider.analyze

    def answer_after_the_sweep(request: Any) -> Any:
        # The worker has claimed its Execution and is mid-flight, which is
        # exactly when the sweep sees a run that has been going too long.
        report = recover_stalled_executions(
            dispatcher.database_url, policy=StalledPolicy(), now=later(hours=2)
        )
        swept.append(report.stalled_executions)
        return original(request)

    dispatcher.provider.analyze = answer_after_the_sweep  # type: ignore[method-assign]
    dispatcher.run_all()

    assert swept == [1], "the sweep should have found the in-flight run"
    database = Database(dispatcher.database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        executions = list(session.scalars(select(Execution)))
        reports = list(session.scalars(select(ZhiyanReport)))
    database.dispose()
    # The answer is kept for tracing and refused as business content. The
    # sweep's verdict stands: overwriting it would erase the record that this
    # run was given up on, which is what the user was told.
    assert reports == []
    # `stale` is the established word for an answer that arrived and was not
    # used, and the sweep's verdict stays readable in the code beside it.
    assert [execution.status for execution in executions] == ["stale"]
    assert [execution.error_code for execution in executions] == [STALLED_CODE]
    assert executions[0].stale_result is not None


def test_a_live_worker_never_masks_a_dead_one(tmp_path: Path) -> None:
    """Two processes fail independently, and beat is the quieter of the two.

    Taking the freshest heartbeat would report a healthy deployment while beat
    was dead and nothing had been cleaned up or recovered for hours.
    """
    client, database_url = _client(tmp_path)
    record_heartbeat(database_url, "liyan-worker")
    record_heartbeat(
        database_url, "liyan-beat", at=datetime.now(UTC) - timedelta(hours=2)
    )

    ready = client.get("/health/ready")

    assert ready.json()["checks"]["worker"] == "silent"
    assert silent_workers(Database(database_url)) == ("liyan-beat",)


def _queued_execution(database_url: str, *, created_at: datetime) -> UUID:
    """One Execution nobody ever collected, as a lost message would leave it."""
    database = Database(database_url)
    assert database.engine is not None
    execution_id = uuid4()
    with Session(database.engine) as session:
        owner = User(email="writer@example.com", auth_subject="supabase-user-1")
        session.add(owner)
        session.flush()
        session.add(
            Execution(
                id=execution_id,
                owner_id=owner.id,
                operation="fetch_url",
                target_type="source_preparation",
                target_id=uuid4(),
                input_version=1,
                input_identity="identity",
                input_snapshot={},
                attempt=1,
                origin="initial",
                status="queued",
                created_at=created_at,
            )
        )
        session.commit()
    database.dispose()
    return execution_id


def test_work_nobody_ever_collected_stops_waiting_forever(tmp_path: Path) -> None:
    """The failure that hid a queue nobody consumed.

    A message can be lost, purged, or addressed to a queue no worker listens on.
    The Execution then sits `queued` — never claimed, so never `running`, so
    invisible to a sweep that only rescues runs in flight — and the 来源 shows
    处理中 until somebody thinks to look in the broker.
    """
    database_url = migrated_database(tmp_path)
    execution_id = _queued_execution(database_url, created_at=datetime.now(UTC))

    report = recover_stalled_executions(
        database_url, policy=StalledPolicy(), now=later(hours=2)
    )

    assert report.stalled_executions == 1
    status, code, _ = _execution(database_url, execution_id)
    assert status == "failed"
    # Distinct from a run that died mid-flight: nothing ever picked this up, and
    # the fix is a worker or a queue name rather than a dead process.
    assert code == NEVER_STARTED_CODE


def test_work_queued_a_moment_ago_is_left_in_the_queue(tmp_path: Path) -> None:
    """A backlog is not a fault; the worker may simply be busy."""
    database_url = migrated_database(tmp_path)
    execution_id = _queued_execution(database_url, created_at=datetime.now(UTC))

    report = recover_stalled_executions(
        database_url, policy=StalledPolicy(), now=later(minutes=5)
    )

    assert report.stalled_executions == 0
    assert _execution(database_url, execution_id)[0] == "queued"


def test_a_failed_run_says_so_in_the_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Silence is the worst thing a failure can do to whoever is watching.

    The workers record why a run failed on the Execution row and, until now,
    logged nothing at all — so an operator with three terminals open saw a
    source turn red and had no thread to pull. The row keeps the detail; the log
    has to at least say that something ended badly, and which row to read.
    """
    client, headers, dispatcher = zhiyan_client(tmp_path)
    confirm_sources(client, headers, ["四天工作制已经没有争议"])
    dispatcher.provider.outcomes.append(unavailable())

    with caplog.at_level(logging.WARNING, logger="liyan_server"):
        dispatcher.run_next()

    failures = [r for r in caplog.records if r.message == "execution_failed"]
    assert failures, "a failed run logged nothing"
    logged = failures[0].__dict__
    assert logged["error_code"] == "provider_unavailable"
    assert logged["operation"] == "analyze_source"
    # The reason itself stays on the row: it can quote whatever it was handed.
    assert "internal_error" not in logged


def test_every_worker_reports_the_failures_it_records() -> None:
    """A structural check, because the omission is what keeps happening.

    Failure logging was added to three of the four workers and missed on the
    fourth, and the gap surfaced the way it always does — someone watching a
    terminal while 立言 generation failed twice in silence. A behavioural test
    per worker would not have caught it either, because the missing one simply
    had no test.

    So this asserts the rule rather than an instance: every module that writes a
    terminal failure onto an Execution also says so. It is coupled to the source
    on purpose. That coupling is the point — a fifth worker cannot be added
    without either logging its failures or failing here.
    """
    workers = [
        "zhiyan/worker.py",
        "liyan/worker.py",
        "url_fetch_worker.py",
        "file_parse_worker.py",
        "publication/worker.py",
    ]
    root = Path(__file__).resolve().parents[1] / "src" / "liyan_server"

    silent = [
        name
        for name in workers
        if 'execution.status = "failed"' in (root / name).read_text()
        and "log_execution_failed" not in (root / name).read_text()
    ]

    assert silent == [], f"these workers fail without saying so: {silent}"
