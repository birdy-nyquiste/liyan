from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient
from zhiyan_support import confirm_sources, zhiyan_client

type JsonObject = dict[str, Any]


def open_edit_session(client: TestClient, headers: dict[str, str], task_id: str) -> JsonObject:
    response = client.post(f"/tasks/{task_id}/source-edit-sessions", headers=headers)
    assert response.status_code == 201, response.text
    return cast(JsonObject, response.json())


def stage_pasted_source(
    client: TestClient,
    headers: dict[str, str],
    edit_session_id: str,
    marker: str,
) -> JsonObject:
    response = client.post(
        "/task-creation/pasted-sources",
        headers=headers,
        json={
            "client_session_id": edit_session_id,
            "client_source_id": marker,
            "title": f"Staged {marker}",
            "body": (f"Staged body {marker}. " * 40).strip(),
            "provenance": f"https://example.com/{marker}",
        },
    )
    assert response.status_code == 201, response.text
    return cast(JsonObject, response.json())


def save_edit_session(
    client: TestClient,
    headers: dict[str, str],
    edit_session_id: str,
    *,
    key: str,
    sources: list[dict[str, object]],
) -> JsonObject:
    response = client.post(
        f"/source-edit-sessions/{edit_session_id}/save",
        headers=headers,
        json={"idempotency_key": key, "sources": sources},
    )
    assert response.status_code == 200, response.text
    return cast(JsonObject, response.json())


def test_source_edits_create_immutable_versions_and_reuse_unchanged_reports(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, ["Alpha", "Beta", "Gamma"])
    dispatcher.run_all()

    first = open_edit_session(client, headers, task_id)
    assert first["base_version"]["number"] == 1
    original_sources = first["base_version"]["sources"]
    assert [source["title"] for source in original_sources] == ["Alpha", "Beta", "Gamma"]
    staged_delta = stage_pasted_source(client, headers, str(first["id"]), "delta")

    version_two = save_edit_session(
        client,
        headers,
        str(first["id"]),
        key="save-v2",
        sources=[
            {
                "source_id": original_sources[0]["source_id"],
                "base_revision_id": original_sources[0]["id"],
            },
            {
                "source_id": original_sources[1]["source_id"],
                "base_revision_id": original_sources[1]["id"],
                "content": {
                    "title": "Beta edited",
                    "body": original_sources[1]["body"] + "\nA direct correction.",
                    "provenance": original_sources[1]["provenance"],
                },
            },
            {"prepared_source_id": staged_delta["id"]},
        ],
    )

    assert version_two["number"] == 2
    assert version_two["is_current"] is True
    assert [source["title"] for source in version_two["sources"]] == [
        "Alpha",
        "Beta edited",
        "Staged delta",
    ]
    assert version_two["sources"][0]["id"] == original_sources[0]["id"]
    assert version_two["sources"][1]["id"] != original_sources[1]["id"]
    assert len(dispatcher.execution_ids) == 2
    dispatcher.run_all()

    version_two_zhiyan = client.get(
        f"/tasks/{task_id}/versions/{version_two['id']}/zhiyan", headers=headers
    ).json()
    report_ids_v2 = {
        source["source_revision_id"]: source["report"]["id"]
        for source in version_two_zhiyan["sources"]
    }
    version_one_zhiyan = client.get(
        f"/tasks/{task_id}/versions/{first['base_version']['id']}/zhiyan", headers=headers
    ).json()
    original_alpha_report = version_one_zhiyan["sources"][0]["report"]["id"]
    assert report_ids_v2[original_sources[0]["id"]] == original_alpha_report
    assert version_one_zhiyan["liyan"] == {
        "can_generate": False,
        "unavailable_reason": "历史任务版本只读，恢复为当前版本后才能继续操作。",
    }
    assert all(
        source["capabilities"]["can_start"] is False
        and source["capabilities"]["can_cancel"] is False
        for source in version_one_zhiyan["sources"]
    )
    historical_start = client.post(
        f"/source-revisions/{original_sources[0]['id']}/zhiyan-runs", headers=headers
    )
    assert historical_start.status_code == 409
    historical_direct = client.get(
        f"/source-revisions/{original_sources[0]['id']}/zhiyan", headers=headers
    ).json()
    assert historical_direct["capabilities"]["can_start"] is False
    assert historical_direct["capabilities"]["can_cancel"] is False

    second = open_edit_session(client, headers, task_id)
    staged_replacement = stage_pasted_source(client, headers, str(second["id"]), "replacement")
    current_sources = second["base_version"]["sources"]
    version_three = save_edit_session(
        client,
        headers,
        str(second["id"]),
        key="save-v3",
        sources=[
            {
                "source_id": current_sources[0]["source_id"],
                "base_revision_id": current_sources[0]["id"],
                "prepared_source_id": staged_replacement["id"],
            },
            {
                "source_id": current_sources[1]["source_id"],
                "base_revision_id": current_sources[1]["id"],
            },
            {
                "source_id": current_sources[2]["source_id"],
                "base_revision_id": current_sources[2]["id"],
            },
        ],
    )
    assert version_three["number"] == 3
    assert version_three["sources"][0]["source_id"] == current_sources[0]["source_id"]
    assert version_three["sources"][0]["id"] != current_sources[0]["id"]
    assert len(dispatcher.execution_ids) == 1
    dispatcher.run_all()

    history = client.get(f"/tasks/{task_id}/versions", headers=headers)
    assert history.status_code == 200
    assert [version["number"] for version in history.json()["items"]] == [3, 2, 1]
    assert history.json()["items"][0]["capabilities"] == {
        "can_edit": True,
        "can_restore": False,
        "unavailable_reason": None,
    }
    assert history.json()["items"][1]["capabilities"]["can_edit"] is False
    assert history.json()["items"][1]["capabilities"]["can_restore"] is True


def test_restoring_history_moves_only_the_current_reference_and_later_edits_branch(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, ["Original"])
    dispatcher.run_all()
    first = open_edit_session(client, headers, task_id)
    source = first["base_version"]["sources"][0]
    second = save_edit_session(
        client,
        headers,
        str(first["id"]),
        key="save-v2",
        sources=[
            {
                "source_id": source["source_id"],
                "base_revision_id": source["id"],
                "content": {
                    "title": "Second",
                    "body": source["body"] + "\nSecond version.",
                    "provenance": source["provenance"],
                },
            }
        ],
    )
    dispatcher.run_all()

    restored = client.post(
        f"/tasks/{task_id}/versions/{first['base_version']['id']}/restore",
        headers=headers,
        json={"idempotency_key": "restore-v1"},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["id"] == first["base_version"]["id"]
    assert restored.json()["number"] == 1
    assert restored.json()["is_current"] is True
    task = client.get("/tasks", headers=headers).json()["items"][0]
    assert task["current_version_id"] == first["base_version"]["id"]
    assert task["current_version_number"] == 1

    branched_session = open_edit_session(client, headers, task_id)
    branched_source = branched_session["base_version"]["sources"][0]
    branched = save_edit_session(
        client,
        headers,
        str(branched_session["id"]),
        key="save-v3",
        sources=[
            {
                "source_id": branched_source["source_id"],
                "base_revision_id": branched_source["id"],
                "content": {
                    "title": "Branched from first",
                    "body": branched_source["body"] + "\nA different branch.",
                    "provenance": branched_source["provenance"],
                },
            }
        ],
    )
    assert branched["number"] == 3
    history = client.get(f"/tasks/{task_id}/versions", headers=headers).json()["items"]
    assert [version["number"] for version in history] == [3, 2, 1]
    assert (
        next(version for version in history if version["number"] == 2)["sources"][0]["title"]
        == second["sources"][0]["title"]
    )


def test_source_edit_save_is_atomic_idempotent_and_owner_scoped(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, ["Owned"])
    dispatcher.run_all()
    edit = open_edit_session(client, headers, task_id)
    source = edit["base_version"]["sources"][0]
    request = {
        "idempotency_key": "one-save",
        "sources": [
            {
                "source_id": source["source_id"],
                "base_revision_id": source["id"],
                "content": {
                    "title": "Changed once",
                    "body": source["body"] + "\nChanged once.",
                    "provenance": source["provenance"],
                },
            }
        ],
    }
    first = client.post(f"/source-edit-sessions/{edit['id']}/save", headers=headers, json=request)
    replay = client.post(f"/source-edit-sessions/{edit['id']}/save", headers=headers, json=request)
    assert first.status_code == replay.status_code == 200
    assert first.json()["id"] == replay.json()["id"]
    assert len(dispatcher.execution_ids) == 1

    conflict = client.post(
        f"/source-edit-sessions/{edit['id']}/save",
        headers=headers,
        json={"idempotency_key": "different", "sources": request["sources"]},
    )
    assert conflict.status_code == 409
    assert len(client.get(f"/tasks/{task_id}/versions", headers=headers).json()["items"]) == 2

    other_headers = {"Authorization": "Bearer second-token"}
    assert (
        client.post(f"/tasks/{task_id}/source-edit-sessions", headers=other_headers).status_code
        == 404
    )
    assert (
        client.post(
            f"/source-edit-sessions/{edit['id']}/discard", headers=other_headers
        ).status_code
        == 404
    )


def test_unfinished_source_edit_session_can_be_discarded_without_a_version(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, ["Stable"])
    dispatcher.run_all()
    edit = open_edit_session(client, headers, task_id)
    discarded = client.post(f"/source-edit-sessions/{edit['id']}/discard", headers=headers)
    assert discarded.status_code == 204
    assert [
        version["number"]
        for version in client.get(f"/tasks/{task_id}/versions", headers=headers).json()["items"]
    ] == [1]
    save = client.post(
        f"/source-edit-sessions/{edit['id']}/save",
        headers=headers,
        json={
            "idempotency_key": "too-late",
            "sources": [
                {
                    "source_id": edit["base_version"]["sources"][0]["source_id"],
                    "base_revision_id": edit["base_version"]["sources"][0]["id"],
                }
            ],
        },
    )
    assert save.status_code == 409


def test_active_runs_noop_saves_and_stale_parallel_sessions_cannot_change_history(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, ["Stable"])
    active = client.post(f"/tasks/{task_id}/source-edit-sessions", headers=headers)
    assert active.status_code == 409
    dispatcher.run_all()

    noop = open_edit_session(client, headers, task_id)
    source = noop["base_version"]["sources"][0]
    unchanged = client.post(
        f"/source-edit-sessions/{noop['id']}/save",
        headers=headers,
        json={
            "idempotency_key": "noop",
            "sources": [
                {"source_id": source["source_id"], "base_revision_id": source["id"]}
            ],
        },
    )
    assert unchanged.status_code == 409
    assert [
        version["number"]
        for version in client.get(f"/tasks/{task_id}/versions", headers=headers).json()["items"]
    ] == [1]

    first = open_edit_session(client, headers, task_id)
    stale = open_edit_session(client, headers, task_id)
    first_source = first["base_version"]["sources"][0]
    save_edit_session(
        client,
        headers,
        str(first["id"]),
        key="winner",
        sources=[
            {
                "source_id": first_source["source_id"],
                "base_revision_id": first_source["id"],
                "content": {
                    "title": "Winner",
                    "body": first_source["body"] + "\nWinner.",
                    "provenance": first_source["provenance"],
                },
            }
        ],
    )
    stale_source = stale["base_version"]["sources"][0]
    loser = client.post(
        f"/source-edit-sessions/{stale['id']}/save",
        headers=headers,
        json={
            "idempotency_key": "loser",
            "sources": [
                {
                    "source_id": stale_source["source_id"],
                    "base_revision_id": stale_source["id"],
                    "content": {
                        "title": "Loser",
                        "body": stale_source["body"] + "\nLoser.",
                        "provenance": stale_source["provenance"],
                    },
                }
            ],
        },
    )
    assert loser.status_code == 409


def test_identical_prepared_replacement_reuses_the_existing_revision(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, ["Same"])
    dispatcher.run_all()
    edit = open_edit_session(client, headers, task_id)
    source = edit["base_version"]["sources"][0]
    prepared = client.post(
        "/task-creation/pasted-sources",
        headers=headers,
        json={
            "client_session_id": edit["id"],
            "client_source_id": "same-again",
            "title": source["title"],
            "body": source["body"],
            "provenance": source["provenance"],
        },
    ).json()
    response = client.post(
        f"/source-edit-sessions/{edit['id']}/save",
        headers=headers,
        json={
            "idempotency_key": "identical",
            "sources": [
                {
                    "source_id": source["source_id"],
                    "base_revision_id": source["id"],
                    "prepared_source_id": prepared["id"],
                    "content": {
                        "title": source["title"],
                        "body": source["body"],
                        "provenance": source["provenance"],
                    },
                }
            ],
            "accepted_warning_versions": {
                prepared["id"]: prepared["input_version"]
            },
        },
    )
    assert response.status_code == 409
    assert dispatcher.execution_ids == []
