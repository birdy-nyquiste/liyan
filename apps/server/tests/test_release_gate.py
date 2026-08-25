"""The Phase 1 release gate: one writer's whole workflow, end to end.

Every other test in this suite proves one rule about one part. That is what a
suite should do, and it is also how a system passes every test and still cannot
be used: each part is correct against its own fixture, and the fixtures never
have to agree with each other. The 来源 a 知言 run reads is built by the 知言
tests; the article a publication locks is built by the publication tests.

This file builds nothing. It signs in, pastes 来源, confirms a 立言任务, waits for
every 知言报告, generates a 立言文章 from those reports, saves a Revision, and
publishes it — each step handing the next only what the API actually returned.
A break anywhere between two features shows up here and nowhere else.

Everything is deterministic: the queue is a recording double a test steps
through, DeepSeek and Blog are doubles, and no test here reaches the network.
The live half of the gate is opt-in and lives in `test_live_stack.py`,
`test_zhiyan_live_contract.py`, and `test_r2_live_contract.py`;
`docs/operations/release-gate.md` says which of them runs when.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from publication_support import SITE_URL, publication_client, submitter_of
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.routing import Match
from zhiyan_support import (
    RecordingDispatcher,
    abandon_run,
    confirm_sources,
    create_session_sources,
    elapse_retry_backoff,
    latest_stored_run,
)

from liyan_server.database import Database, Execution
from liyan_server.publication.blog import BlogOutcomeUnknown, BlogSubmissionFailure

SECOND = {"Authorization": "Bearer second-token"}
SOURCES = ["四天工作制已经没有争议", "试验数据被反复引用"]
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def walk_to_reports(
    client: TestClient, headers: dict[str, str], dispatcher: RecordingDispatcher
) -> tuple[str, list[str]]:
    """Sign-in through 知言: the half of the workflow that precedes any article."""
    task_id, revision_ids = confirm_sources(client, headers, SOURCES)
    assert len(dispatcher.execution_ids) == len(SOURCES)
    dispatcher.run_all()
    for revision_id in revision_ids:
        state = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers)
        assert state.status_code == 200, state.text
        assert state.json()["status"] == "succeeded"
    return task_id, revision_ids


def generate_article(
    client: TestClient,
    headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    task_id: str,
    *,
    key: str = "generate-1",
) -> dict[str, Any]:
    started = client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={
            "idempotency_key": key,
            "instruction": {"content": [{"type": "text", "text": "写得更克制一些。"}]},
        },
    )
    assert started.status_code == 202, started.text
    dispatcher.run_all()
    state = client.get(f"/tasks/{task_id}/liyan", headers=headers)
    assert state.status_code == 200, state.text
    payload: dict[str, Any] = state.json()
    assert payload["status"] == "succeeded", payload
    return payload


def test_one_writer_goes_from_pasted_sources_to_a_blog_preview(tmp_path: Path) -> None:
    """The whole workflow, each step fed only by what the previous one returned."""
    client, headers, dispatcher = publication_client(tmp_path)

    task_id, revision_ids = walk_to_reports(client, headers, dispatcher)

    liyan = generate_article(client, headers, dispatcher, task_id)
    result = liyan["result"]
    saved = client.post(
        f"/tasks/{task_id}/liyan-revisions",
        headers=headers,
        json={
            "idempotency_key": "save-1",
            "base_revision_id": None,
            "title": result["title"],
            "body_markdown": result["body_markdown"],
        },
    )
    assert saved.status_code == 201, saved.text
    revision = saved.json()["revisions"]["current"]

    eligible = client.get("/publication/eligible-articles", headers=headers)
    assert eligible.status_code == 200, eligible.text
    offered = [article for article in eligible.json()["items"] if article["task_id"] == task_id]
    assert [article["revision_id"] for article in offered] == [revision["id"]]

    published = client.post(
        "/publication/publish-tasks",
        headers=headers,
        json={
            "idempotency_key": "publish-1",
            "task_id": task_id,
            "revision_id": revision["id"],
            "target_key": "lsforum",
            "author": "Zeng Zong",
            "working_copy_hash": revision["content_hash"],
        },
    )
    assert published.status_code == 202, published.text
    dispatcher.run_all()

    publish_task = client.get(
        f"/publication/publish-tasks/{published.json()['id']}", headers=headers
    )
    assert publish_task.status_code == 200, publish_task.text
    terminal = publish_task.json()
    assert terminal["status"] == "succeeded"
    assert terminal["preview_url"].startswith(SITE_URL)

    # Publication is not completion: the 立言任务 stays open for more work.
    workspace = client.get("/tasks", headers=headers)
    assert workspace.status_code == 200, workspace.text
    assert task_id in [task["id"] for task in workspace.json()["items"]]
    assert len(revision_ids) == len(SOURCES)


def test_the_whole_workflow_is_invisible_to_a_second_writer(tmp_path: Path) -> None:
    """Ownership holds at every step, not only where a test remembered to check.

    One user's task, version, reports, article, Revisions, and 发布任务 are all
    read through ids the other user can guess as easily as type. Each of these
    is refused somewhere in the per-feature suites; what this asks is whether
    every door of one finished workflow is locked at once.
    """
    client, headers, dispatcher = publication_client(tmp_path)
    task_id, revision_ids = walk_to_reports(client, headers, dispatcher)
    generate_article(client, headers, dispatcher, task_id)
    saved = client.post(
        f"/tasks/{task_id}/liyan-revisions",
        headers=headers,
        json={
            "idempotency_key": "save-1",
            "base_revision_id": None,
            "title": "四天工作制的真问题",
            "body_markdown": "工时只是生产方式的一部分。",
        },
    )
    revision_id = saved.json()["revisions"]["current"]["id"]
    published = client.post(
        "/publication/publish-tasks",
        headers=headers,
        json={
            "idempotency_key": "publish-1",
            "task_id": task_id,
            "revision_id": revision_id,
            "target_key": "lsforum",
            "author": "Zeng Zong",
        },
    )
    dispatcher.run_all()
    publish_task_id = published.json()["id"]

    for method, path in [
        ("GET", f"/tasks/{task_id}/zhiyan"),
        ("GET", f"/source-revisions/{revision_ids[0]}/zhiyan"),
        ("POST", f"/source-revisions/{revision_ids[0]}/zhiyan-runs"),
        ("GET", f"/tasks/{task_id}/liyan"),
        ("GET", f"/tasks/{task_id}/versions"),
        ("GET", f"/publication/publish-tasks/{publish_task_id}"),
    ]:
        response = client.request(method, path, headers=SECOND)
        assert response.status_code == 404, f"{method} {path} answered {response.status_code}"

    # And nothing of the first writer's leaks into the second's own workspace.
    assert client.get("/tasks", headers=SECOND).json()["items"] == []
    assert client.get("/publication/eligible-articles", headers=SECOND).json()["items"] == []


def test_a_run_can_be_cancelled_and_the_workflow_continues_from_there(
    tmp_path: Path,
) -> None:
    """Cancellation is a step in a workflow, not an end to it."""
    client, headers, dispatcher = publication_client(tmp_path)
    _, revision_ids = confirm_sources(client, headers, SOURCES)
    queued = latest_stored_run(dispatcher.database_url, revision_ids[0])

    cancelled = client.post(f"/executions/{queued.id}/cancel", headers=headers)
    assert cancelled.status_code == 202, cancelled.text
    dispatcher.run_all()

    state = client.get(f"/source-revisions/{revision_ids[0]}/zhiyan", headers=headers)
    assert state.json()["status"] == "cancelled"
    assert state.json()["capabilities"]["can_start"] is True

    restarted = client.post(f"/source-revisions/{revision_ids[0]}/zhiyan-runs", headers=headers)
    assert restarted.status_code == 202, restarted.text
    dispatcher.run_all()
    assert (
        client.get(f"/source-revisions/{revision_ids[0]}/zhiyan", headers=headers).json()["status"]
        == "succeeded"
    )


def test_a_failed_run_is_retried_into_the_same_workflow(tmp_path: Path) -> None:
    client, headers, dispatcher = publication_client(tmp_path)
    _, revision_ids = confirm_sources(client, headers, SOURCES)
    dispatcher.execution_ids.clear()
    failed = latest_stored_run(dispatcher.database_url, revision_ids[0])
    abandon_run(dispatcher.database_url, str(failed.id))
    elapse_retry_backoff(dispatcher.database_url, revision_ids[0])

    retried = client.post(f"/source-revisions/{revision_ids[0]}/zhiyan-runs", headers=headers)

    assert retried.status_code == 202, retried.text
    dispatcher.run_all()
    state = client.get(f"/source-revisions/{revision_ids[0]}/zhiyan", headers=headers)
    assert state.json()["status"] == "succeeded"


def test_every_publication_outcome_is_terminal_in_the_way_the_product_promises(
    tmp_path: Path,
) -> None:
    """The three ways a 发布任务 ends, from three complete workflows.

    A Preview is the terminal success; a definitive refusal may be sent again
    because nothing was created; 结果未知 may never be resent, because Blog may
    hold something 立言阁 cannot see (ADR-0001).
    """
    outcomes: dict[str, tuple[Exception | None, str, bool]] = {
        "preview": (None, "succeeded", False),
        "refused": (
            BlogSubmissionFailure("provider_rejected", "Blog 暂时无法提交，请稍后重试。"),
            "failed",
            True,
        ),
        "unknown": (BlogOutcomeUnknown("Blog responded 502."), "outcome_unknown", False),
    }
    for label, (failure, expected_status, retryable) in outcomes.items():
        environment = tmp_path / label
        environment.mkdir()
        client, headers, dispatcher = publication_client(environment)
        task_id, _ = walk_to_reports(client, headers, dispatcher)
        generate_article(client, headers, dispatcher, task_id)
        saved = client.post(
            f"/tasks/{task_id}/liyan-revisions",
            headers=headers,
            json={
                "idempotency_key": f"save-{label}",
                "base_revision_id": None,
                "title": "四天工作制的真问题",
                "body_markdown": "工时只是生产方式的一部分。",
            },
        )
        revision_id = saved.json()["revisions"]["current"]["id"]
        if failure is not None:
            dispatcher.blog.outcomes.append(failure)
        published = client.post(
            "/publication/publish-tasks",
            headers=headers,
            json={
                "idempotency_key": f"publish-{label}",
                "task_id": task_id,
                "revision_id": revision_id,
                "target_key": "lsforum",
                "author": "Zeng Zong",
            },
        )
        assert published.status_code == 202, published.text
        dispatcher.run_all()

        publish_task_id = published.json()["id"]
        record = client.get(
            f"/publication/publish-tasks/{publish_task_id}", headers=headers
        ).json()
        assert record["status"] == expected_status, (label, record)

        # Whether it may be sent again is proved by trying, not by reading a flag.
        resent = client.post(
            f"/publication/publish-tasks/{publish_task_id}/retry",
            headers=headers,
            json={"idempotency_key": f"retry-{label}", "acknowledge_existing_preview": False},
        )
        assert (resent.status_code == 202) is retryable, (label, resent.text)


def test_a_deleted_task_takes_its_work_and_leaves_its_publication_evidence(
    tmp_path: Path,
) -> None:
    """Deletion at the end of a workflow, with a Preview already created.

    What a user submitted to a platform is not theirs alone to erase: the
    Preview is a real Blog item, so the evidence of it outlives the 立言任务.
    """
    client, headers, dispatcher = publication_client(tmp_path)
    task_id, _ = walk_to_reports(client, headers, dispatcher)
    generate_article(client, headers, dispatcher, task_id)
    saved = client.post(
        f"/tasks/{task_id}/liyan-revisions",
        headers=headers,
        json={
            "idempotency_key": "save-1",
            "base_revision_id": None,
            "title": "四天工作制的真问题",
            "body_markdown": "工时只是生产方式的一部分。",
        },
    )
    revision_id = saved.json()["revisions"]["current"]["id"]
    published = client.post(
        "/publication/publish-tasks",
        headers=headers,
        json={
            "idempotency_key": "publish-1",
            "task_id": task_id,
            "revision_id": revision_id,
            "target_key": "lsforum",
            "author": "Zeng Zong",
        },
    )
    dispatcher.run_all()
    assert published.status_code == 202, published.text

    deleted = client.request(
        "DELETE", f"/tasks/{task_id}", headers=headers, json={"confirmed": True}
    )
    assert deleted.status_code == 204, deleted.text

    remaining = [task["id"] for task in client.get("/tasks", headers=headers).json()["items"]]
    assert task_id not in remaining
    assert client.get(f"/tasks/{task_id}/liyan", headers=headers).status_code == 404
    evidence = client.get("/publication/publish-tasks", headers=headers).json()["items"]
    assert [record["task_id"] for record in evidence] == [task_id]
    assert evidence[0]["preview_url"].startswith(SITE_URL)


def test_one_active_run_per_source_revision_is_a_constraint_not_a_check(
    tmp_path: Path,
) -> None:
    """The 知言 rule holds against a race, because the database holds it.

    The API reads the current run and then decides, which is check-then-act:
    two requests that both read "nothing active" would both decide to proceed.
    What stops the second is a partial unique index, and the only way to show
    that is to go around the API and ask the database directly.
    """
    client, headers, dispatcher = publication_client(tmp_path)
    _, revision_ids = confirm_sources(client, headers, SOURCES)
    revision_id = UUID(revision_ids[0])

    database = Database(dispatcher.database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        queued = session.scalars(
            select(Execution).where(Execution.target_id == revision_id)
        ).one()
        session.add(
            Execution(
                owner_id=queued.owner_id,
                operation=queued.operation,
                target_type=queued.target_type,
                target_id=queued.target_id,
                input_version=queued.input_version,
                input_identity=queued.input_identity,
                input_snapshot=queued.input_snapshot,
                attempt=queued.attempt + 1,
                origin="manual",
                status="queued",
                created_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    database.dispose()


def test_replaying_every_key_in_the_workflow_creates_nothing_twice(tmp_path: Path) -> None:
    """A dropped response is the normal case, not the exotic one.

    A phone that loses signal mid-request retries all four of these keys, and
    each one guards something a second copy of would be visible to a user: a
    duplicate 立言任务, a duplicate run charged to DeepSeek, a duplicate Revision
    in history, a duplicate Blog item that cannot be retracted.
    """
    client, headers, dispatcher = publication_client(tmp_path)
    source_ids = create_session_sources(client, headers, SOURCES, client_session_id="s1")
    confirmation = {
        "idempotency_key": "confirm-1",
        "client_session_id": "s1",
        "source_ids": source_ids,
    }
    first = client.post("/task-creation/confirm", headers=headers, json=confirmation)
    replayed = client.post("/task-creation/confirm", headers=headers, json=confirmation)
    assert replayed.status_code == 200, replayed.text
    task_id = first.json()["task"]["id"]
    assert replayed.json()["task"]["id"] == task_id
    dispatcher.run_all()

    generation = {
        "idempotency_key": "generate-1",
        "instruction": {"content": [{"type": "text", "text": "写得更克制一些。"}]},
    }
    assert client.post(
        f"/tasks/{task_id}/liyan-runs", headers=headers, json=generation
    ).status_code == 202
    replayed_run = client.post(f"/tasks/{task_id}/liyan-runs", headers=headers, json=generation)
    assert replayed_run.status_code == 202, replayed_run.text
    assert not dispatcher.execution_ids[1:], "A replayed generation queued a second run."
    dispatcher.run_all()

    save = {
        "idempotency_key": "save-1",
        "base_revision_id": None,
        "title": "四天工作制的真问题",
        "body_markdown": "工时只是生产方式的一部分。",
    }
    saved = client.post(f"/tasks/{task_id}/liyan-revisions", headers=headers, json=save)
    replayed_save = client.post(f"/tasks/{task_id}/liyan-revisions", headers=headers, json=save)
    assert replayed_save.status_code in {200, 201}, replayed_save.text
    revision = saved.json()["revisions"]["current"]
    assert replayed_save.json()["revisions"]["current"]["id"] == revision["id"]
    assert replayed_save.json()["revisions"]["historical"] == []

    publication = {
        "idempotency_key": "publish-1",
        "task_id": task_id,
        "revision_id": revision["id"],
        "target_key": "lsforum",
        "author": "Zeng Zong",
    }
    published = client.post("/publication/publish-tasks", headers=headers, json=publication)
    replayed_publication = client.post(
        "/publication/publish-tasks", headers=headers, json=publication
    )
    assert replayed_publication.json()["id"] == published.json()["id"]
    dispatcher.run_all()
    assert len(submitter_of(dispatcher).submissions) == 1


def test_article_history_holds_the_workflow_and_can_be_walked_back(tmp_path: Path) -> None:
    """Saving, bounded history, and restoration, on the article the workflow made."""
    client, headers, dispatcher = publication_client(tmp_path)
    task_id, _ = walk_to_reports(client, headers, dispatcher)
    generate_article(client, headers, dispatcher, task_id)

    base: str | None = None
    saved_ids: list[str] = []
    for index in range(5):
        saved = client.post(
            f"/tasks/{task_id}/liyan-revisions",
            headers=headers,
            json={
                "idempotency_key": f"save-{index}",
                "base_revision_id": base,
                "title": f"四天工作制的真问题 {index}",
                "body_markdown": f"第 {index} 次修改后的正文。",
            },
        )
        assert saved.status_code == 201, saved.text
        base = saved.json()["revisions"]["current"]["id"]
        saved_ids.append(base)

    history = client.get(f"/tasks/{task_id}/liyan", headers=headers).json()["revisions"]
    assert history["current"]["id"] == saved_ids[-1]
    assert len(history["historical"]) == 3, history

    oldest_kept = history["historical"][-1]["id"]
    restored = client.post(
        f"/tasks/{task_id}/liyan-revisions/{oldest_kept}/restore",
        headers=headers,
        json={"idempotency_key": "restore-1"},
    )
    assert restored.status_code == 201, restored.text
    current = restored.json()["revisions"]["current"]
    assert current["id"] not in saved_ids, "Restoring must create a new Revision, not reuse one."
    assert current["restored_from_revision_id"] == oldest_kept


def test_two_simultaneous_requests_never_double_one_step_of_the_workflow(
    tmp_path: Path,
) -> None:
    """Two tabs, one workflow. Each step admits one and refuses the other.

    Sequential on purpose: what is being checked is that the second request is
    refused at all, which is the refusal a user meets. That the refusals also
    survive a genuine race is a separate claim, and it is proved where it lives
    — against the constraint itself, below — because two requests through one
    TestClient cannot interleave.
    """
    client, headers, dispatcher = publication_client(tmp_path)
    task_id, revision_ids = confirm_sources(client, headers, SOURCES)

    # A 知言 run is already queued for every Revision, so a second is refused.
    second_run = client.post(f"/source-revisions/{revision_ids[0]}/zhiyan-runs", headers=headers)
    assert second_run.status_code == 409, second_run.text
    dispatcher.run_all()
    generate_article(client, headers, dispatcher, task_id)
    saved = client.post(
        f"/tasks/{task_id}/liyan-revisions",
        headers=headers,
        json={
            "idempotency_key": "save-1",
            "base_revision_id": None,
            "title": "四天工作制的真问题",
            "body_markdown": "工时只是生产方式的一部分。",
        },
    )
    revision = saved.json()["revisions"]["current"]

    # Two saves from the same base: the second is stale, not a silent overwrite.
    stale = client.post(
        f"/tasks/{task_id}/liyan-revisions",
        headers=headers,
        json={
            "idempotency_key": "save-2",
            "base_revision_id": None,
            "title": "另一个标题",
            "body_markdown": "另一份正文。",
        },
    )
    assert stale.status_code == 409, stale.text

    # Two publications of one Revision to one target: one Blog item, ever.
    first = client.post(
        "/publication/publish-tasks",
        headers=headers,
        json={
            "idempotency_key": "publish-1",
            "task_id": task_id,
            "revision_id": revision["id"],
            "target_key": "lsforum",
            "author": "Zeng Zong",
        },
    )
    assert first.status_code == 202, first.text
    duplicate = client.post(
        "/publication/publish-tasks",
        headers=headers,
        json={
            "idempotency_key": "publish-2",
            "task_id": task_id,
            "revision_id": revision["id"],
            "target_key": "lsforum",
            "author": "Zeng Zong",
        },
    )
    assert duplicate.status_code == 409, duplicate.text
    dispatcher.run_all()
    assert len(submitter_of(dispatcher).submissions) == 1


def test_the_whole_workflow_stays_inside_the_published_openapi(tmp_path: Path) -> None:
    """Every route this workflow uses is in the contract the workbench is built from.

    `npm run api:check` proves `openapi.json` still matches the application.
    This proves the other direction: that the path a user actually takes lies
    inside it. A route reachable but undocumented is a route the generated
    client cannot call, which is a workbench that cannot ship.

    The paths are collected from the requests, not listed by hand. A list would
    be a second copy of the workflow, free to keep asserting about steps the
    workflow no longer takes.
    """
    client, headers, dispatcher = publication_client(tmp_path)
    requested = record_requested_routes(client)

    task_id, _ = walk_to_reports(client, headers, dispatcher)
    generate_article(client, headers, dispatcher, task_id)
    saved = client.post(
        f"/tasks/{task_id}/liyan-revisions",
        headers=headers,
        json={
            "idempotency_key": "save-1",
            "base_revision_id": None,
            "title": "四天工作制的真问题",
            "body_markdown": "工时只是生产方式的一部分。",
        },
    )
    client.get("/publication/eligible-articles", headers=headers)
    published = client.post(
        "/publication/publish-tasks",
        headers=headers,
        json={
            "idempotency_key": "publish-1",
            "task_id": task_id,
            "revision_id": saved.json()["revisions"]["current"]["id"],
            "target_key": "lsforum",
            "author": "Zeng Zong",
        },
    )
    dispatcher.run_all()
    client.get(f"/publication/publish-tasks/{published.json()['id']}", headers=headers)

    documented = set(json.loads((PROJECT_ROOT / "openapi.json").read_text())["paths"])

    # A recorder that silently stops matching would turn this into a test that
    # asserts nothing, so the count is part of the claim.
    assert len(requested) >= 8, sorted(requested)
    assert requested <= documented, requested - documented


def record_requested_routes(client: TestClient) -> set[str]:
    """Collect the route templates a client is about to exercise.

    Templates rather than URLs: `/tasks/{task_id}/liyan` is what the contract
    names, and the concrete id in a request is not. Starlette can already say
    which of its routes a request matched, so the matching is asked of it
    rather than reimplemented against the path text.
    """
    routes: set[str] = set()
    # Flattened, because an included router is itself a route with routes
    # inside it, and only the leaves carry a path the contract names.
    leaves = list(_leaf_routes(client.app.routes))  # type: ignore[attr-defined]

    def note(request: Any) -> None:
        scope = {
            "type": "http",
            "method": request.method,
            "path": request.url.path,
            "path_params": {},
            "headers": [],
            "root_path": "",
        }
        for route in leaves:
            match, _ = route.matches(scope)
            if match is Match.FULL:
                routes.add(route.path)
                return

    client.event_hooks["request"].append(note)
    return routes


def _leaf_routes(routes: Any) -> Iterator[Any]:
    """Every route that names a path, however many routers deep it sits.

    FastAPI wraps an included router in a route of its own, which carries no
    path and keeps the real ones on `original_router`. Only the leaves name a
    path the contract can document.
    """
    for route in routes:
        included = getattr(route, "original_router", None)
        nested = getattr(route, "routes", None)
        if included is not None:
            yield from _leaf_routes(included.routes)
        elif nested:
            yield from _leaf_routes(nested)
        elif hasattr(route, "path"):
            yield route
