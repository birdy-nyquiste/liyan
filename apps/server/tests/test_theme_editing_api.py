"""编辑主题: the 主题 is a field of a 来源编辑会话, saved with the 来源.

A 主题 edit is a change like any other — it produces a new 任务版本, editing a 来源
makes the 主题 owe a new report even when its text did not move, and clearing the
主题 is the way out of a report that will not succeed.

提炼主题 is here too. Its 来源 arrive with the press rather than being read from
rows: an editing session's 来源 are the version's revisions plus whatever the
writer has typed over them, and that last part is in the browser until it is
saved. A press that re-read the rows would answer about text the writer has
already replaced.
"""

from pathlib import Path
from typing import Any, cast

from fastapi.testclient import TestClient
from zhiyan_support import (
    DEFAULT_THEME,
    RecordingDispatcher,
    confirm_sources,
    unavailable,
    zhiyan_client,
)

from liyan_server.theme.prompt import THEME_FORMAT_NAME

TITLES = ["四天工作制已经没有争议", "试验数据被反复引用"]
OTHER_THEME = "四天工作制对班次制行业的适用性"


def task_with_theme(
    tmp_path: Path,
) -> tuple[TestClient, dict[str, str], RecordingDispatcher, str]:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, TITLES, theme=DEFAULT_THEME)
    dispatcher.run_all()
    return client, headers, dispatcher, task_id


def edit_session(client: TestClient, headers: dict[str, str], task_id: str) -> dict[str, Any]:
    opened = client.post(f"/tasks/{task_id}/source-edit-sessions", headers=headers)
    assert opened.status_code == 201, opened.text
    return cast(dict[str, Any], opened.json())


def unchanged_sources(base: dict[str, Any]) -> list[dict[str, object]]:
    return [
        {"source_id": source["source_id"], "base_revision_id": source["id"]}
        for source in base["base_version"]["sources"]
    ]


def save(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    *,
    key: str,
    sources: list[dict[str, object]],
    theme: str | None,
) -> Any:
    return client.post(
        f"/source-edit-sessions/{session_id}/save",
        headers=headers,
        json={"idempotency_key": key, "sources": sources, "theme": theme},
    )


def theme_state(client: TestClient, headers: dict[str, str], task_id: str) -> Any:
    return client.get(f"/tasks/{task_id}/zhiyan", headers=headers).json()["theme"]


def test_the_edit_session_shows_the_current_theme(tmp_path: Path) -> None:
    client, headers, dispatcher, task_id = task_with_theme(tmp_path)

    opened = edit_session(client, headers, task_id)

    assert opened["base_version"]["theme"] == DEFAULT_THEME


def test_editing_only_the_theme_is_a_change_and_creates_a_version(tmp_path: Path) -> None:
    """Without this, the one part of a version a user can edit alone was refused."""
    client, headers, dispatcher, task_id = task_with_theme(tmp_path)
    opened = edit_session(client, headers, task_id)

    saved = save(
        client,
        headers,
        opened["id"],
        key="edit-1",
        sources=unchanged_sources(opened),
        theme=OTHER_THEME,
    )

    assert saved.status_code == 200, saved.text
    assert saved.json()["number"] == 2
    assert saved.json()["theme"] == OTHER_THEME
    # A new 主题 owes a new report, and the 来源 keep theirs.
    assert len(dispatcher.execution_ids) == 1
    dispatcher.run_all()
    assert theme_state(client, headers, task_id)["theme"] == OTHER_THEME
    assert theme_state(client, headers, task_id)["status"] == "succeeded"


def test_saving_the_same_theme_and_sources_is_still_refused_as_nothing_staged(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id = task_with_theme(tmp_path)
    opened = edit_session(client, headers, task_id)

    refused = save(
        client,
        headers,
        opened["id"],
        key="edit-1",
        sources=unchanged_sources(opened),
        theme=DEFAULT_THEME,
    )

    assert refused.status_code == 409


def test_editing_a_source_makes_the_unchanged_theme_owe_a_new_report(
    tmp_path: Path,
) -> None:
    """The run read those 来源, so its 盲点 is a statement about that set.

    This is the asymmetry with a 来源 report, and it is deliberate: an unchanged
    来源 keeps its report because that report cannot be affected by its
    neighbours, and a 主题 report is about the whole set.
    """
    client, headers, dispatcher, task_id = task_with_theme(tmp_path)
    opened = edit_session(client, headers, task_id)
    sources = unchanged_sources(opened)
    first = opened["base_version"]["sources"][0]
    sources[0] = {
        "source_id": first["source_id"],
        "base_revision_id": first["id"],
        "content": {
            "title": first["title"],
            "body": first["body"] + "补充了一段新的材料。" * 5,
            "provenance": first["provenance"],
        },
    }

    saved = save(
        client, headers, opened["id"], key="edit-1", sources=sources, theme=DEFAULT_THEME
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["theme"] == DEFAULT_THEME

    # One changed 来源 and the 主题 that was measured against it: two runs.
    assert len(dispatcher.execution_ids) == 2
    dispatcher.run_all()
    theme_requests = [
        sent for sent in dispatcher.provider.requests if sent.format_name == THEME_FORMAT_NAME
    ]
    assert len(theme_requests) == 2
    assert "补充了一段新的材料" in theme_requests[1].input_text


def test_restoring_a_version_reuses_its_existing_theme_report(tmp_path: Path) -> None:
    client, headers, dispatcher, task_id = task_with_theme(tmp_path)
    opened = edit_session(client, headers, task_id)
    base_version_id = opened["base_version"]["id"]
    save(
        client,
        headers,
        opened["id"],
        key="edit-1",
        sources=unchanged_sources(opened),
        theme=OTHER_THEME,
    )
    dispatcher.run_all()

    restored = client.post(
        f"/tasks/{task_id}/versions/{base_version_id}/restore",
        headers=headers,
        json={"idempotency_key": "restore-1"},
    )

    assert restored.status_code == 200, restored.text
    assert restored.json()["theme"] == DEFAULT_THEME
    # Nothing is queued: that snapshot's report already exists.
    assert dispatcher.execution_ids == []
    assert theme_state(client, headers, task_id)["status"] == "succeeded"


def test_clearing_the_theme_reopens_liyan(tmp_path: Path) -> None:
    """The one way past a 主题 report that will not succeed."""
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, TITLES, theme=DEFAULT_THEME)
    dispatcher.provider.theme_outcomes.extend([unavailable(), unavailable()])
    dispatcher.run_all()
    blocked = client.get(f"/tasks/{task_id}/zhiyan", headers=headers).json()
    assert blocked["liyan"]["can_generate"] is False

    opened = edit_session(client, headers, task_id)
    saved = save(
        client,
        headers,
        opened["id"],
        key="edit-1",
        sources=unchanged_sources(opened),
        theme=None,
    )

    assert saved.status_code == 200, saved.text
    assert saved.json()["theme"] is None
    assert dispatcher.execution_ids == []
    reopened = client.get(f"/tasks/{task_id}/zhiyan", headers=headers).json()
    assert reopened["theme"] is None
    assert reopened["liyan"]["can_generate"] is True


def test_clearing_the_theme_gives_the_task_its_sources_title_back(tmp_path: Path) -> None:
    client, headers, dispatcher, task_id = task_with_theme(tmp_path)
    opened = edit_session(client, headers, task_id)

    save(
        client,
        headers,
        opened["id"],
        key="edit-1",
        sources=unchanged_sources(opened),
        theme=None,
    )

    listed = client.get("/tasks", headers=headers).json()
    assert listed["items"][0]["display_name"] == TITLES[0]


def test_a_running_theme_analysis_blocks_editing(tmp_path: Path) -> None:
    """As a running 来源 analysis does: saving underneath it would strand the report."""
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, TITLES, theme=DEFAULT_THEME)
    dispatcher.run_next()
    dispatcher.run_next()  # both 来源 analyses; the 主题 run stays queued

    refused = client.post(f"/tasks/{task_id}/source-edit-sessions", headers=headers)

    assert refused.status_code == 409
    assert "暂时不能编辑" in refused.json()["detail"]


def press_in_edit_session(
    client: TestClient,
    headers: dict[str, str],
    edit_id: str,
    sources: list[dict[str, object]],
) -> Any:
    return client.post(
        "/task-creation/theme-proposals",
        headers=headers,
        json={"client_session_id": edit_id, "sources": sources},
    )


def drafts_of(base: dict[str, Any]) -> list[dict[str, object]]:
    return [
        {
            "title": source["title"],
            "body": source["body"],
            "provenance": source["provenance"],
        }
        for source in base["base_version"]["sources"]
    ]


def test_提炼主题_reads_the_drafts_the_press_carries(tmp_path: Path) -> None:
    """Including text that is not a row anywhere yet."""
    client, headers, dispatcher, task_id = task_with_theme(tmp_path)
    opened = edit_session(client, headers, task_id)
    drafts = drafts_of(opened)
    drafts[0]["body"] = f"{drafts[0]['body']}（这一段还没有保存）"

    started = press_in_edit_session(client, headers, opened["id"], drafts)
    assert started.status_code == 202, started.text
    dispatcher.run_all()

    proposal = client.get(
        f"/task-creation/theme-proposals/{started.json()['id']}", headers=headers
    )
    assert proposal.json()["status"] == "succeeded"
    assert len(proposal.json()["candidates"]) == 3
    request = next(
        sent
        for sent in dispatcher.provider.requests
        if sent.format_name == "theme_candidates"
    )
    assert "这一段还没有保存" in request.input_text


def test_提炼主题_needs_an_editing_session_of_this_users_own(tmp_path: Path) -> None:
    """Otherwise the endpoint would be a way to have an Agent read any text at
    all under somebody's account, charged to them."""
    client, headers, dispatcher, task_id = task_with_theme(tmp_path)
    opened = edit_session(client, headers, task_id)
    drafts = drafts_of(opened)

    assert press_in_edit_session(client, headers, "not-a-session", drafts).status_code == 404
    denied = client.post(
        "/task-creation/theme-proposals",
        headers={"Authorization": "Bearer second-token"},
        json={"client_session_id": opened["id"], "sources": drafts},
    )
    assert denied.status_code == 404


def test_提炼主题_refuses_a_press_carrying_no_sources(tmp_path: Path) -> None:
    client, headers, dispatcher, task_id = task_with_theme(tmp_path)
    opened = edit_session(client, headers, task_id)

    refused = press_in_edit_session(client, headers, opened["id"], [])

    assert refused.status_code == 422
    assert "一到三个来源" in refused.json()["detail"]


def test_提炼主题_refuses_more_text_than_one_press_may_carry(tmp_path: Path) -> None:
    client, headers, dispatcher, task_id = task_with_theme(tmp_path)
    opened = edit_session(client, headers, task_id)
    drafts = drafts_of(opened)
    drafts[0]["body"] = "四" * 500_001

    refused = press_in_edit_session(client, headers, opened["id"], drafts)

    assert refused.status_code == 422
    assert "过长" in refused.json()["detail"]


def test_a_press_from_an_editing_session_is_not_refused_when_sources_change(
    tmp_path: Path,
) -> None:
    """A creation session's press is refused if its 来源 changed under it, because
    the rows can be compared. Here there is nothing to compare: the snapshot is
    the only record of what was asked, so the answer stands."""
    client, headers, dispatcher, task_id = task_with_theme(tmp_path)
    opened = edit_session(client, headers, task_id)
    started = press_in_edit_session(client, headers, opened["id"], drafts_of(opened))
    # A 来源 is staged into the same session before the run gets to it.
    staged = client.post(
        "/task-creation/pasted-sources",
        headers=headers,
        json={
            "client_session_id": opened["id"],
            "client_source_id": "staged-1",
            "title": "另一个来源",
            "body": "四天工作制的排班成本被反复低估。" * 40,
            "provenance": "https://press.example/staged",
        },
    )
    assert staged.status_code == 201, staged.text
    dispatcher.run_all()

    proposal = client.get(
        f"/task-creation/theme-proposals/{started.json()['id']}", headers=headers
    )
    assert proposal.json()["status"] == "succeeded"
