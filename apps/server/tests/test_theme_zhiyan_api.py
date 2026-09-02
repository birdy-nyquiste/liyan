"""One 主题知言报告 for one 主题 snapshot, and the 立言 gate it belongs to.

主题 is a special 来源: version-scoped, immutable, one report, and it counts in the
same gate. What this file proves is that it behaves that way — including at the
two edges where it does not resemble a 来源 at all: an empty 主题 changes nothing
about a task, and a 主题 whose report keeps failing has exactly one way out.
"""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from zhiyan_support import (
    DEFAULT_THEME,
    THEME_OPENED_URL,
    RecordingDispatcher,
    confirm_sources,
    elapse_retry_backoff,
    theme_revision_id,
    unavailable,
    zhiyan_client,
)

from liyan_server.theme.prompt import THEME_FORMAT_NAME
from liyan_server.theme.runs import THEME_OPERATION

TITLES = ["四天工作制已经没有争议", "试验数据被反复引用"]


def task_with_theme(
    tmp_path: Path,
    theme: str | None = DEFAULT_THEME,
) -> tuple[TestClient, dict[str, str], RecordingDispatcher, str]:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, TITLES, theme=theme)
    return client, headers, dispatcher, task_id


def zhiyan_area(client: TestClient, headers: dict[str, str], task_id: str) -> Any:
    state = client.get(f"/tasks/{task_id}/zhiyan", headers=headers)
    assert state.status_code == 200, state.text
    return state.json()


def test_confirming_with_a_theme_queues_its_own_run_beside_the_sources(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id = task_with_theme(tmp_path)

    # Two 来源 and one 主题: three runs from one confirmation.
    assert len(dispatcher.execution_ids) == 3
    dispatcher.run_all()

    area = zhiyan_area(client, headers, task_id)
    assert area["theme"]["theme"] == DEFAULT_THEME
    assert area["theme"]["status"] == "succeeded"
    assert area["theme"]["report"]["document"]["blind_spots"]["items"][0]["id"] == "TB-01"
    assert area["theme"]["report"]["document"]["evidence"]["items"][0]["url"] == THEME_OPENED_URL


def test_the_theme_run_reads_the_theme_and_every_source_of_its_version(
    tmp_path: Path,
) -> None:
    """The 来源 are the baseline `blind_spots` is measured against, so they travel."""
    client, headers, dispatcher, _ = task_with_theme(tmp_path)
    dispatcher.run_all()

    request = next(
        sent for sent in dispatcher.provider.requests if sent.format_name == THEME_FORMAT_NAME
    )
    assert DEFAULT_THEME in request.input_text
    for title in TITLES:
        assert title in request.input_text
    assert request.tool_policy.web_search_enabled is True


def test_liyan_stays_shut_until_the_theme_report_is_in(tmp_path: Path) -> None:
    client, headers, dispatcher, task_id = task_with_theme(tmp_path)

    # Run the two 来源 analyses and leave the 主题 one queued.
    dispatcher.run_next()
    dispatcher.run_next()
    area = zhiyan_area(client, headers, task_id)
    assert all(source["status"] == "succeeded" for source in area["sources"])
    assert area["liyan"]["can_generate"] is False

    dispatcher.run_all()
    assert zhiyan_area(client, headers, task_id)["liyan"]["can_generate"] is True


def test_a_failed_theme_report_says_how_to_get_past_it(tmp_path: Path) -> None:
    """The gate names the way out, because there is exactly one and it is obscure.

    Every 来源 has its report, so nothing about the 来源 will ever change; the
    only thing that reopens 立言 is clearing the 主题 in a 来源编辑会话.
    """
    client, headers, dispatcher, task_id = task_with_theme(tmp_path)
    dispatcher.provider.theme_outcomes.extend([unavailable(), unavailable()])
    dispatcher.run_all()

    area = zhiyan_area(client, headers, task_id)
    assert area["theme"]["status"] == "failed"
    assert area["liyan"]["can_generate"] is False
    assert "清空主题" in area["liyan"]["unavailable_reason"]


def test_a_task_with_no_theme_is_gated_on_its_sources_alone(tmp_path: Path) -> None:
    """Every task that existed before 主题 did, and every one confirmed without one."""
    client, headers, dispatcher, task_id = task_with_theme(tmp_path, theme=None)

    assert len(dispatcher.execution_ids) == 2
    dispatcher.run_all()

    area = zhiyan_area(client, headers, task_id)
    assert area["theme"] is None
    assert area["liyan"]["can_generate"] is True


def test_an_empty_theme_is_a_legitimate_confirmation(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)

    task_id, _ = confirm_sources(client, headers, TITLES, theme="   ")

    assert zhiyan_area(client, headers, task_id)["theme"] is None


def test_a_theme_over_eighty_characters_is_refused(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    from zhiyan_support import create_session_sources

    source_ids = create_session_sources(client, headers, TITLES)
    refused = client.post(
        "/task-creation/confirm",
        headers=headers,
        json={
            "idempotency_key": "key-1",
            "client_session_id": "session-1",
            "source_ids": source_ids,
            "theme": "四" * 81,
        },
    )

    assert refused.status_code == 422
    assert "80" in refused.json()["detail"]


def test_the_theme_becomes_the_tasks_name(tmp_path: Path) -> None:
    client, headers, dispatcher, task_id = task_with_theme(tmp_path)

    listed = client.get("/tasks", headers=headers).json()

    assert listed["items"][0]["display_name"] == DEFAULT_THEME


def test_a_task_without_a_theme_keeps_its_first_sources_title(tmp_path: Path) -> None:
    client, headers, dispatcher, task_id = task_with_theme(tmp_path, theme=None)

    listed = client.get("/tasks", headers=headers).json()

    assert listed["items"][0]["display_name"] == TITLES[0]


def test_a_failed_theme_run_may_be_retried_and_then_succeeds(tmp_path: Path) -> None:
    client, headers, dispatcher, task_id = task_with_theme(tmp_path)
    # Both of the initial operation's runs fail: the first and its one automatic
    # recovery attempt.
    dispatcher.provider.theme_outcomes.extend([unavailable(), unavailable()])
    dispatcher.run_all()

    area = zhiyan_area(client, headers, task_id)
    assert area["theme"]["status"] == "failed"
    assert area["theme"]["execution"]["error"]["code"] == "busy"
    assert area["theme"]["capabilities"]["can_start"] is False, "the backoff has not elapsed"

    revision_id = area["theme"]["theme_revision_id"]
    elapse_retry_backoff(dispatcher.database_url, revision_id, operation=THEME_OPERATION)
    started = client.post(f"/theme-revisions/{revision_id}/zhiyan-runs", headers=headers)
    assert started.status_code == 202, started.text
    dispatcher.run_all()

    assert zhiyan_area(client, headers, task_id)["theme"]["status"] == "succeeded"


def test_a_theme_report_cannot_be_regenerated(tmp_path: Path) -> None:
    """Immutable, exactly as a 来源's report is: asking again returns the conflict."""
    client, headers, dispatcher, task_id = task_with_theme(tmp_path)
    dispatcher.run_all()
    revision_id = theme_revision_id(client, headers, task_id)

    refused = client.post(f"/theme-revisions/{revision_id}/zhiyan-runs", headers=headers)

    assert refused.status_code == 409
    assert "已生成" in refused.json()["detail"]


def test_a_running_theme_run_may_be_cancelled(tmp_path: Path) -> None:
    client, headers, dispatcher, task_id = task_with_theme(tmp_path)
    area = zhiyan_area(client, headers, task_id)
    execution_id = area["theme"]["execution"]["id"]
    assert area["theme"]["capabilities"]["can_cancel"] is True

    cancelled = client.post(f"/executions/{execution_id}/cancel", headers=headers)

    assert cancelled.status_code == 202
    assert zhiyan_area(client, headers, task_id)["theme"]["status"] == "cancelled"


def test_another_users_theme_cannot_be_run(tmp_path: Path) -> None:
    client, headers, dispatcher, task_id = task_with_theme(tmp_path)
    revision_id = theme_revision_id(client, headers, task_id)

    denied = client.post(
        f"/theme-revisions/{revision_id}/zhiyan-runs",
        headers={"Authorization": "Bearer second-token"},
    )

    assert denied.status_code == 404
