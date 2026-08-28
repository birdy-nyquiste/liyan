"""One user may not hold the whole queue.

There is one worker slot, and every other bound in this system is per target:
one active 知言 run per source Revision, one active parse per 来源. None of them
stops one user from opening five 立言任务 and putting fifteen runs in front of
everybody else's first request. This is the bound that does, and these are the
two halves of it that matter — that it refuses at the ceiling, and that it never
refuses halfway through something the user already started.
"""

from pathlib import Path
from typing import Any

from database_support import entitle, migrated_database
from fastapi.testclient import TestClient
from zhiyan_support import (
    DeterministicJwtVerifier,
    RecordingDispatcher,
    abandon_run,
    confirm_sources,
    create_session_sources,
    elapse_retry_backoff,
    latest_stored_run,
    source_body,
)

from liyan_server.app import create_app
from liyan_server.execution_limits import AT_CAPACITY_MESSAGE
from liyan_server.settings import Settings

HEADERS = {"Authorization": "Bearer allowed-token"}
SECOND = {"Authorization": "Bearer second-token"}


def capped_client(
    tmp_path: Path, limit: int = 2
) -> tuple[TestClient, RecordingDispatcher]:
    """A workbench whose ceiling is low enough to reach in a test."""
    database_url = migrated_database(tmp_path)
    entitle(database_url)
    dispatcher = RecordingDispatcher(database_url)
    client = TestClient(
        create_app(
            Settings(
                database_url=database_url,
                allowed_emails="writer@example.com,second@example.com",
                max_active_executions_per_user=limit,
            ),
            jwt_verifier=DeterministicJwtVerifier(),
            execution_dispatcher=dispatcher,
        )
    )
    return client, dispatcher


def confirm(
    client: TestClient,
    headers: dict[str, str],
    titles: list[str],
    *,
    key: str,
    session_id: str,
) -> Any:
    """Confirm a creation session, returning the raw response for inspection."""
    source_ids = create_session_sources(client, headers, titles, client_session_id=session_id)
    return client.post(
        "/task-creation/confirm",
        headers=headers,
        json={
            "idempotency_key": key,
            "client_session_id": session_id,
            "source_ids": source_ids,
        },
    )


def test_a_user_holding_the_ceiling_is_refused_with_a_reason(tmp_path: Path) -> None:
    """Two queued 知言 runs is the ceiling here, so the next task is refused."""
    client, dispatcher = capped_client(tmp_path, limit=2)
    confirm_sources(client, HEADERS, ["A", "B"], idempotency_key="key-1")
    assert len(dispatcher.execution_ids) == 2

    refused = confirm(client, HEADERS, ["C"], key="key-2", session_id="session-2")

    assert refused.status_code == 429, refused.text
    assert refused.json()["detail"] == AT_CAPACITY_MESSAGE
    assert len(dispatcher.execution_ids) == 2


def test_work_that_started_under_the_ceiling_is_admitted_whole(tmp_path: Path) -> None:
    """A 任务版本 is never left with some sources analyzed and some not.

    The user is one under the line when they confirm three 来源, and all three
    runs follow from that single act. Refusing the second and third would leave
    a version half analyzed for a reason the user never chose, so the batch is
    admitted whole and the real bound is the ceiling plus one batch.
    """
    client, dispatcher = capped_client(tmp_path, limit=2)
    confirm_sources(client, HEADERS, ["A"], idempotency_key="key-1")
    assert len(dispatcher.execution_ids) == 1

    admitted = confirm(client, HEADERS, ["B", "C", "D"], key="key-2", session_id="session-2")

    assert admitted.status_code == 200, admitted.text
    assert len(dispatcher.execution_ids) == 4


def test_finishing_the_work_gives_the_capacity_back(tmp_path: Path) -> None:
    client, dispatcher = capped_client(tmp_path, limit=2)
    confirm_sources(client, HEADERS, ["A", "B"], idempotency_key="key-1")
    assert confirm(client, HEADERS, ["C"], key="key-2", session_id="session-2").status_code == 429

    dispatcher.run_all()

    accepted = confirm(client, HEADERS, ["C"], key="key-3", session_id="session-3")
    assert accepted.status_code == 200, accepted.text


def test_one_users_queue_never_refuses_another_user(tmp_path: Path) -> None:
    """The ceiling is per user; sharing it would make one writer stop the rest."""
    client, _ = capped_client(tmp_path, limit=2)
    confirm_sources(client, HEADERS, ["A", "B"], idempotency_key="key-1")

    other = confirm(client, SECOND, ["C"], key="key-2", session_id="session-2")

    assert other.status_code == 200, other.text


def test_a_replayed_confirmation_is_never_refused_by_the_ceiling(tmp_path: Path) -> None:
    """Idempotency outranks the ceiling: a replay starts nothing new.

    The runs a confirmation queued are exactly what puts its own user at the
    ceiling, so a client that retries the request after a dropped response
    would be told it is too busy to repeat something already done.
    """
    client, _ = capped_client(tmp_path, limit=2)
    source_ids = create_session_sources(client, HEADERS, ["A", "B"], client_session_id="s1")
    body = {
        "idempotency_key": "key-1",
        "client_session_id": "s1",
        "source_ids": source_ids,
    }
    first = client.post("/task-creation/confirm", headers=HEADERS, json=body)
    assert first.status_code == 200, first.text

    replay = client.post("/task-creation/confirm", headers=HEADERS, json=body)

    assert replay.status_code == 200, replay.text
    assert replay.json()["task"]["id"] == first.json()["task"]["id"]


def test_a_url_source_is_refused_before_anything_is_queued(tmp_path: Path) -> None:
    client, dispatcher = capped_client(tmp_path, limit=2)
    confirm_sources(client, HEADERS, ["A", "B"], idempotency_key="key-1")

    refused = client.post(
        "/task-creation/url-sources",
        headers=HEADERS,
        json={
            "client_session_id": "session-2",
            "client_source_id": "source-0",
            "url": "https://press.example/story",
        },
    )

    assert refused.status_code == 429, refused.text
    assert len(dispatcher.execution_ids) == 2


def test_a_zhiyan_retry_is_refused_while_the_users_other_work_is_queued(
    tmp_path: Path,
) -> None:
    """A retry is new work, and new work waits behind the user's own queue.

    The per-Revision rule cannot see this: that run is failed, so nothing about
    this Revision objects. What objects is everything else the user has running.
    """
    client, dispatcher = capped_client(tmp_path, limit=2)
    _, revision_ids = confirm_sources(client, HEADERS, ["A", "B", "C"], idempotency_key="key-1")
    assert len(dispatcher.execution_ids) == 3
    failed = latest_stored_run(dispatcher.database_url, revision_ids[0])
    abandon_run(dispatcher.database_url, str(failed.id))
    elapse_retry_backoff(dispatcher.database_url, revision_ids[0])

    refused = client.post(f"/source-revisions/{revision_ids[0]}/zhiyan-runs", headers=HEADERS)

    assert refused.status_code == 429, refused.text
    assert refused.json()["detail"] == AT_CAPACITY_MESSAGE


def test_a_ceiling_of_zero_is_no_ceiling(tmp_path: Path) -> None:
    """Local runs one user against one worker and competes with nobody."""
    client, dispatcher = capped_client(tmp_path, limit=0)

    confirm_sources(client, HEADERS, ["A", "B", "C"], idempotency_key="key-1")
    admitted = client.post(
        "/task-creation/pasted-sources",
        headers=HEADERS,
        json={
            "client_session_id": "session-2",
            "client_source_id": "source-0",
            "title": "D",
            "body": source_body("D"),
            "provenance": "https://press.example/d",
        },
    )

    assert admitted.status_code == 201, admitted.text
    assert len(dispatcher.execution_ids) == 3
