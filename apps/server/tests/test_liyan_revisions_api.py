"""Explicit Save, stale-base rejection, bounded history, and restoration."""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from zhiyan_support import confirm_sources, zhiyan_client

SOURCES = ["四天工作制已经没有争议"]

BODY = "工时只是生产方式的一部分。\n\n## 现实条件\n\n改变流程比压缩时间更重要。"


def _ready_task(tmp_path: Path) -> tuple[TestClient, dict[str, str], str, Any]:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, SOURCES)
    dispatcher.run_all()
    return client, headers, task_id, dispatcher


def _save(
    client: TestClient,
    headers: dict[str, str],
    task_id: str,
    *,
    key: str,
    title: str,
    body: str = BODY,
    base_revision_id: str | None = None,
) -> Any:
    return client.post(
        f"/tasks/{task_id}/liyan-revisions",
        headers=headers,
        json={
            "idempotency_key": key,
            "base_revision_id": base_revision_id,
            "title": title,
            "body_markdown": body,
        },
    )


def test_only_an_explicit_save_records_canonical_content_and_task_version_identity(
    tmp_path: Path,
) -> None:
    client, headers, task_id, _ = _ready_task(tmp_path)
    before = client.get(f"/tasks/{task_id}/liyan", headers=headers)
    assert before.status_code == 200, before.text
    assert before.json()["revisions"]["current"] is None

    saved = _save(client, headers, task_id, key="save-1", title="四天工作制的真问题")

    assert saved.status_code == 201, saved.text
    current = saved.json()["revisions"]["current"]
    assert current["number"] == 1
    assert current["title"] == "四天工作制的真问题"
    assert current["body_markdown"] == BODY
    assert current["task_version_id"] == saved.json()["task_version_id"]
    assert current["base_revision_id"] is None
    assert current["restored_from_revision_id"] is None


def test_a_generated_or_recovered_article_never_becomes_a_revision_on_its_own(
    tmp_path: Path,
) -> None:
    client, headers, task_id, dispatcher = _ready_task(tmp_path)

    started = client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={"idempotency_key": "generate-1"},
    )
    assert started.status_code == 202, started.text
    dispatcher.run_all()

    state = client.get(f"/tasks/{task_id}/liyan", headers=headers)
    assert state.json()["status"] == "succeeded"
    assert state.json()["result"] is not None
    assert state.json()["revisions"] == {
        "current": None,
        "historical": [],
        "historical_limit": 3,
    }
    assert state.json()["capabilities"]["publishable_revision_id"] is None


def test_a_stale_base_revision_is_rejected_without_changing_stored_history(
    tmp_path: Path,
) -> None:
    client, headers, task_id, _ = _ready_task(tmp_path)
    first = _save(client, headers, task_id, key="save-1", title="第一版").json()
    base = first["revisions"]["current"]["id"]
    second = _save(
        client, headers, task_id, key="save-2", title="第二版", base_revision_id=base
    )
    assert second.status_code == 201, second.text

    stale = _save(
        client,
        headers,
        task_id,
        key="save-3",
        title="另一个标签页的版本",
        base_revision_id=base,
    )

    assert stale.status_code == 409
    assert stale.json()["detail"] == "文章已有更新的 Revision，请先查看最新内容。"
    state = client.get(f"/tasks/{task_id}/liyan", headers=headers)
    assert state.json()["revisions"]["current"]["title"] == "第二版"
    assert len(state.json()["revisions"]["historical"]) == 1


def test_the_first_save_of_an_existing_article_must_also_declare_its_base(
    tmp_path: Path,
) -> None:
    client, headers, task_id, _ = _ready_task(tmp_path)
    _save(client, headers, task_id, key="save-1", title="第一版")

    without_base = _save(client, headers, task_id, key="save-2", title="覆盖")

    assert without_base.status_code == 409


def test_history_shows_the_current_revision_and_at_most_three_historical_ones(
    tmp_path: Path,
) -> None:
    client, headers, task_id, _ = _ready_task(tmp_path)
    base: str | None = None
    for number in range(1, 7):
        saved = _save(
            client,
            headers,
            task_id,
            key=f"save-{number}",
            title=f"第{number}版",
            base_revision_id=base,
        )
        assert saved.status_code == 201, saved.text
        base = saved.json()["revisions"]["current"]["id"]

    history = client.get(f"/tasks/{task_id}/liyan", headers=headers).json()["revisions"]

    assert history["current"]["title"] == "第6版"
    assert history["historical_limit"] == 3
    assert [item["title"] for item in history["historical"]] == ["第5版", "第4版", "第3版"]


def test_restoring_a_historical_revision_creates_a_new_current_one_with_provenance(
    tmp_path: Path,
) -> None:
    client, headers, task_id, _ = _ready_task(tmp_path)
    first = _save(client, headers, task_id, key="save-1", title="第一版").json()
    original = first["revisions"]["current"]["id"]
    _save(
        client,
        headers,
        task_id,
        key="save-2",
        title="第二版",
        base_revision_id=original,
    )

    restored = client.post(
        f"/tasks/{task_id}/liyan-revisions/{original}/restore",
        headers=headers,
        json={"idempotency_key": "restore-1"},
    )

    assert restored.status_code == 201, restored.text
    revisions = restored.json()["revisions"]
    assert revisions["current"]["number"] == 3
    assert revisions["current"]["title"] == "第一版"
    assert revisions["current"]["restored_from_revision_id"] == original
    assert [item["title"] for item in revisions["historical"]] == ["第二版", "第一版"]


def test_only_the_newest_revision_without_unsaved_edits_is_eligible_for_publication(
    tmp_path: Path,
) -> None:
    client, headers, task_id, _ = _ready_task(tmp_path)
    first = _save(client, headers, task_id, key="save-1", title="第一版").json()
    older = first["revisions"]["current"]["id"]
    second = _save(
        client,
        headers,
        task_id,
        key="save-2",
        title="第二版",
        base_revision_id=older,
    ).json()
    newest = second["revisions"]["current"]
    assert second["capabilities"]["publishable_revision_id"] == newest["id"]

    matched = client.get(
        f"/tasks/{task_id}/liyan",
        headers=headers,
        params={"working_copy_hash": newest["content_hash"]},
    )
    edited = client.get(
        f"/tasks/{task_id}/liyan",
        headers=headers,
        params={"working_copy_hash": "0" * 64},
    )

    assert matched.json()["capabilities"]["publishable_revision_id"] == newest["id"]
    assert edited.json()["capabilities"]["publishable_revision_id"] is None
    assert edited.json()["capabilities"]["publication_unavailable_reason"] == (
        "有未保存的修改，请先保存后再发布。"
    )


def test_a_save_is_rejected_when_it_leaves_the_canonical_markdown_subset(
    tmp_path: Path,
) -> None:
    client, headers, task_id, _ = _ready_task(tmp_path)

    rejected = _save(
        client,
        headers,
        task_id,
        key="save-1",
        title="第一版",
        body="<script>alert(1)</script>",
    )

    assert rejected.status_code == 422
    assert rejected.json()["detail"] == "文章内容超出了可保存的 Markdown 范围。"


def test_replaying_one_save_idempotency_key_does_not_create_a_second_revision(
    tmp_path: Path,
) -> None:
    client, headers, task_id, _ = _ready_task(tmp_path)
    first = _save(client, headers, task_id, key="save-1", title="第一版")

    replay = _save(client, headers, task_id, key="save-1", title="第一版")

    assert replay.status_code == 201
    assert replay.json()["revisions"]["current"]["id"] == (
        first.json()["revisions"]["current"]["id"]
    )
    assert replay.json()["revisions"]["historical"] == []


def test_another_user_cannot_read_or_save_revisions_for_a_task_they_do_not_own(
    tmp_path: Path,
) -> None:
    client, headers, task_id, _ = _ready_task(tmp_path)
    _save(client, headers, task_id, key="save-1", title="第一版")
    intruder = {"Authorization": "Bearer second-token"}

    assert client.get(f"/tasks/{task_id}/liyan", headers=intruder).status_code == 404
    assert _save(client, intruder, task_id, key="save-x", title="入侵").status_code == 404


def test_one_save_key_cannot_be_reused_for_different_article_content(
    tmp_path: Path,
) -> None:
    client, headers, task_id, _ = _ready_task(tmp_path)
    _save(client, headers, task_id, key="save-1", title="第一版")

    reused = _save(client, headers, task_id, key="save-1", title="另一篇文章")

    assert reused.status_code == 409
    assert reused.json()["detail"] == "相同幂等键不能用于不同的立言请求。"


def test_restoring_the_current_revision_is_refused_as_a_duplicate(tmp_path: Path) -> None:
    client, headers, task_id, _ = _ready_task(tmp_path)
    current = _save(client, headers, task_id, key="save-1", title="第一版").json()
    current_id = current["revisions"]["current"]["id"]

    refused = client.post(
        f"/tasks/{task_id}/liyan-revisions/{current_id}/restore",
        headers=headers,
        json={"idempotency_key": "restore-1"},
    )

    assert refused.status_code == 409
    assert refused.json()["detail"] == "该 Revision 已经是当前版本。"


def test_one_restore_key_cannot_be_reused_for_a_different_revision(tmp_path: Path) -> None:
    client, headers, task_id, _ = _ready_task(tmp_path)
    first = _save(client, headers, task_id, key="save-1", title="第一版").json()
    original = first["revisions"]["current"]["id"]
    second = _save(
        client, headers, task_id, key="save-2", title="第二版", base_revision_id=original
    ).json()
    other = second["revisions"]["current"]["id"]
    client.post(
        f"/tasks/{task_id}/liyan-revisions/{original}/restore",
        headers=headers,
        json={"idempotency_key": "restore-1"},
    )

    reused = client.post(
        f"/tasks/{task_id}/liyan-revisions/{other}/restore",
        headers=headers,
        json={"idempotency_key": "restore-1"},
    )

    assert reused.status_code == 409
    assert reused.json()["detail"] == "相同幂等键不能用于不同的立言请求。"


def test_a_revision_can_be_saved_while_a_liyan_run_is_still_active(tmp_path: Path) -> None:
    client, headers, task_id, _ = _ready_task(tmp_path)
    started = client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={"idempotency_key": "generate-1"},
    )
    assert started.status_code == 202
    assert started.json()["capabilities"]["can_save"] is True

    saved = _save(client, headers, task_id, key="save-1", title="生成期间保存的草稿")

    assert saved.status_code == 201, saved.text
    assert saved.json()["revisions"]["current"]["title"] == "生成期间保存的草稿"
