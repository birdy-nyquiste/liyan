"""The whole system, wired the way it actually runs, against real processes.

Every other test in this suite substitutes a double for the queue, which is
exactly why a real bug could hide there: the API dispatched to `source-
processing` while the worker consumed Celery's default queue, and nothing failed
— the API answered 202, the queue filled, and every 来源 sat at 处理中 forever.
Beat disguised it, because its own tasks went to the default queue and ran.

Two tests can catch that class of fault: this one, and production. So this one
starts a real Celery worker against a real broker and a real database, and
watches an Execution actually cross the gap.

Three gates, because they cost different things:

    LIYAN_LIVE_STACK=1      real PostgreSQL, Redis, Celery worker.   Free.
    LIYAN_LIVE_PROVIDERS=1  adds a real 知言 run through DeepSeek.   Spends money.

Blog has a gate of its own, in `test_blog_live_contract.py`, and not because it
is tidier there: a Preview is a real item on a real Blog, 立言阁 cannot retract
one, and v0.11 offers no way to look one up again (ADR-0001). A gate that
irreversible should not be something another check can turn on by including it.
"""

import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy
from database_support import migrated_database
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from zhiyan_support import DeterministicJwtVerifier

from liyan_server.app import create_app
from liyan_server.database import Database, Execution
from liyan_server.settings import Settings

REQUIRES_STACK = pytest.mark.skipif(
    os.environ.get("LIYAN_LIVE_STACK") != "1",
    reason="Set LIYAN_LIVE_STACK=1, with PostgreSQL and Redis up, for the live stack check.",
)
REQUIRES_PROVIDERS = pytest.mark.skipif(
    os.environ.get("LIYAN_LIVE_PROVIDERS") != "1",
    reason="Set LIYAN_LIVE_PROVIDERS=1 to spend real DeepSeek credit in this check.",
)

HEADERS = {"Authorization": "Bearer allowed-token"}
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _broker_url() -> str:
    return os.environ.get("LIYAN_BROKER_URL", "redis://localhost:6379/0")


def _live_database() -> str:
    """A real PostgreSQL, because a worker subprocess cannot share a SQLite file."""
    configured = os.environ.get("LIYAN_TEST_DATABASE_URL", "").strip()
    if not configured:
        pytest.skip("Set LIYAN_TEST_DATABASE_URL to a PostgreSQL server for the live stack.")
    return configured


@pytest.fixture
def stack(tmp_path: Path) -> Iterator[tuple[TestClient, str]]:
    """An API and a real worker, both pointed at one fresh database."""
    os.environ["LIYAN_TEST_DATABASE_URL"] = _live_database()
    database_url = migrated_database(tmp_path)
    settings = Settings(
        database_url=database_url,
        broker_url=_broker_url(),
        allowed_emails="writer@example.com",
    )
    client = TestClient(
        create_app(settings, jwt_verifier=DeterministicJwtVerifier())
    )
    worker = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "liyan_server.celery_worker",
            "worker",
            "--loglevel=warning",
            "--concurrency=1",
        ],
        cwd=PROJECT_ROOT,
        env=os.environ
        | {
            "LIYAN_DATABASE_URL": database_url,
            "LIYAN_BROKER_URL": _broker_url(),
            # A name of its own, so a heartbeat from this run is identifiable.
            "LIYAN_WORKER_NAME": "live-stack-check",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        yield client, database_url
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=15)
        except subprocess.TimeoutExpired:
            worker.kill()


def _await_execution(
    database_url: str, *, leaves: str, seconds: int = 90
) -> list[Execution]:
    """Wait until at least one Execution is no longer in `leaves`."""
    database = Database(database_url)
    assert database.engine is not None
    deadline = time.monotonic() + seconds
    found: list[Execution] = []
    try:
        while time.monotonic() < deadline:
            with Session(database.engine) as session:
                found = list(session.scalars(select(Execution)))
                if found and any(row.status != leaves for row in found):
                    return found
            time.sleep(0.5)
    finally:
        database.dispose()
    return found


@REQUIRES_STACK
def test_a_real_worker_collects_what_the_api_really_dispatched(
    stack: tuple[TestClient, str],
) -> None:
    """The gap no doubled dispatcher can cover.

    What matters here is not that the fetch succeeds — crawl4ai may be absent
    and the URL may not resolve. It is that the Execution stops being `queued`,
    which can only happen if a real worker took a real message off a real queue
    and looked it up in the same database the API wrote it to.
    """
    client, database_url = stack

    created = client.post(
        "/task-creation/url-sources",
        headers=HEADERS,
        json={
            "client_session_id": "live-1",
            "client_source_id": "source-1",
            "url": "https://example.com/",
        },
    )
    assert created.status_code == 201, created.text

    executions = _await_execution(database_url, leaves="queued")

    assert executions, "the API dispatched nothing"
    assert any(row.status != "queued" for row in executions), (
        "the worker never collected the message — check that its queue matches "
        "EXECUTION_QUEUE, which is the failure this test exists for"
    )


@REQUIRES_STACK
def test_a_real_worker_reports_its_heartbeat(stack: tuple[TestClient, str]) -> None:
    """Readiness claims a worker is beating; this is where that becomes true."""
    client, database_url = stack

    client.post(
        "/task-creation/url-sources",
        headers=HEADERS,
        json={
            "client_session_id": "live-2",
            "client_source_id": "source-1",
            "url": "https://example.com/",
        },
    )
    _await_execution(database_url, leaves="queued")

    engine = sqlalchemy.create_engine(database_url)
    try:
        with engine.connect() as connection:
            beats = connection.execute(
                sqlalchemy.text("select worker from worker_heartbeats")
            ).scalars()
            assert "live-stack-check" in list(beats)
    finally:
        engine.dispose()


@REQUIRES_STACK
@REQUIRES_PROVIDERS
def test_a_real_zhiyan_run_produces_a_real_report(stack: tuple[TestClient, str]) -> None:
    """Costs DeepSeek credit. Proves the provider contract against the live API.

    The offline suite replays a captured response, which keeps the acceptance
    rules honest but cannot notice the model changing what it sends.
    """
    client, database_url = stack

    confirmation = _confirm_pasted_task(client)
    task_id = confirmation["task"]["id"]

    deadline = time.monotonic() + 420
    overview: dict[str, Any] = {}
    while time.monotonic() < deadline:
        overview = client.get(f"/tasks/{task_id}/zhiyan", headers=HEADERS).json()
        statuses = [source["status"] for source in overview["sources"]]
        if all(status in {"succeeded", "failed"} for status in statuses):
            break
        time.sleep(3)

    assert overview["sources"], "no 知言 run was started"
    assert overview["sources"][0]["status"] == "succeeded", overview["sources"][0]
    assert overview["sources"][0]["report"]["document"]["overview"]["content_summary"]


def _confirm_pasted_task(client: TestClient) -> dict[str, Any]:
    created = client.post(
        "/task-creation/pasted-sources",
        headers=HEADERS,
        json={
            "client_session_id": "live-3",
            "client_source_id": "source-1",
            "title": "四天工作制已经没有争议",
            "body": (
                "所有企业实行四天工作制后，营收都会增长35%。"
                "英国的试验已经证明了这一点，政府应当立即全面强制实施。"
                "反对者提出的成本问题在试验数据面前站不住脚。"
            ),
        },
    )
    assert created.status_code == 201, created.text
    source = created.json()
    confirmed = client.post(
        "/task-creation/confirm",
        headers=HEADERS,
        json={
            "idempotency_key": "live-confirm-1",
            "client_session_id": "live-3",
            "source_ids": [source["id"]],
            # This 来源 is deliberately short — it is the worked example the
            # Agent Spec analyses — so intake warns about it, and confirmation
            # refuses until the warning is answered. A user answers it by
            # deciding the 来源 is complete; so does this.
            "accepted_warning_versions": {source["id"]: source["input_version"]},
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    result: dict[str, Any] = confirmed.json()
    return result
