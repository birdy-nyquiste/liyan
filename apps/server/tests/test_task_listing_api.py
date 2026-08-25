from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from liyan_server.database import Database, Task
from zhiyan_support import confirm_sources, zhiyan_client


def test_task_list_rejects_a_malformed_cursor(tmp_path: Path) -> None:
    client, headers, _ = zhiyan_client(tmp_path)

    response = client.get("/tasks", headers=headers, params={"cursor": "a"})

    assert response.status_code == 422
    assert response.json()["detail"] == "The task cursor is invalid."


def test_tasks_are_cursor_paginated_by_recent_activity_with_a_stable_boundary(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    first_id, _ = confirm_sources(
        client, headers, ["First"], idempotency_key="first", client_session_id="first"
    )
    second_id, _ = confirm_sources(
        client, headers, ["Second"], idempotency_key="second", client_session_id="second"
    )
    third_id, _ = confirm_sources(
        client, headers, ["Third"], idempotency_key="third", client_session_id="third"
    )

    database = Database(dispatcher.database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        tasks = {
            str(task.id): task
            for task in session.scalars(
                select(Task).where(
                    Task.id.in_([UUID(first_id), UUID(second_id), UUID(third_id)])
                )
            )
        }
        moment = datetime(2026, 8, 25, 12, tzinfo=UTC)
        tasks[first_id].last_activity_at = moment
        tasks[second_id].last_activity_at = moment + timedelta(minutes=1)
        tasks[third_id].last_activity_at = moment + timedelta(minutes=2)
        session.commit()

    first_page = client.get("/tasks?limit=2", headers=headers)
    assert first_page.status_code == 200, first_page.text
    assert [item["id"] for item in first_page.json()["items"]] == [third_id, second_id]
    assert first_page.json()["next_cursor"]
    assert all("last_activity_at" in item for item in first_page.json()["items"])

    second_page = client.get(
        "/tasks",
        headers=headers,
        params={"limit": 2, "cursor": first_page.json()["next_cursor"]},
    )
    assert second_page.status_code == 200, second_page.text
    assert [item["id"] for item in second_page.json()["items"]] == [first_id]
    assert second_page.json()["next_cursor"] is None


def test_rename_moves_a_task_to_the_front_without_publication_activity_semantics(
    tmp_path: Path,
) -> None:
    client, headers, _ = zhiyan_client(tmp_path)
    first_id, _ = confirm_sources(
        client, headers, ["First"], idempotency_key="first", client_session_id="first"
    )
    second_id, _ = confirm_sources(
        client, headers, ["Second"], idempotency_key="second", client_session_id="second"
    )

    renamed = client.patch(
        f"/tasks/{first_id}", headers=headers, json={"display_name": "Renamed"}
    )

    assert renamed.status_code == 200, renamed.text
    tasks = client.get("/tasks", headers=headers).json()["items"]
    assert [task["id"] for task in tasks] == [first_id, second_id]
    assert renamed.json()["last_activity_at"] == tasks[0]["last_activity_at"]
