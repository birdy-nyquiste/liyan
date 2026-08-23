from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from fastapi.testclient import TestClient
from publication_support import publication_client, publish, saved_article
from pytest import MonkeyPatch
from sqlalchemy import select
from sqlalchemy.orm import Session
from zhiyan_support import accepted_result, confirm_sources, zhiyan_client

from liyan_server.database import Database, Execution, LiyanRunResult, ZhiyanReport
from liyan_server.liyan.provider import LiyanProviderResult, LiyanRequest
from liyan_server.zhiyan.provider import ZhiyanProviderResult, ZhiyanRequest


class ApiResponse(Protocol):
    @property
    def status_code(self) -> int: ...

    @property
    def text(self) -> str: ...

    def json(self) -> Any: ...


def delete_task(client: TestClient, headers: dict[str, str], task_id: str) -> ApiResponse:
    return client.request(
        "DELETE",
        f"/tasks/{task_id}",
        headers=headers,
        json={"confirmed": True},
    )


def test_deletion_requires_confirmation_hides_the_task_and_keeps_its_number_spent(
    tmp_path: Path,
) -> None:
    client, headers, _ = zhiyan_client(tmp_path)
    first_id, _ = confirm_sources(client, headers, ["First"])

    unconfirmed = client.request(
        "DELETE", f"/tasks/{first_id}", headers=headers, json={"confirmed": False}
    )
    deleted = delete_task(client, headers, first_id)
    second_id, _ = confirm_sources(
        client,
        headers,
        ["Second"],
        idempotency_key="create-second",
        client_session_id="session-2",
    )

    assert unconfirmed.status_code == 422
    assert deleted.status_code == 204, deleted.text
    assert client.get(f"/tasks/{first_id}/current-version", headers=headers).status_code == 404
    tasks = client.get("/tasks", headers=headers).json()["items"]
    assert [(item["id"], item["number"]) for item in tasks] == [(second_id, 2)]


def test_a_nonterminal_publication_blocks_deletion_without_calling_blog(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = publication_client(tmp_path)
    task_id, revision = saved_article(client, headers, dispatcher)
    started = publish(client, headers, task_id=task_id, revision_id=revision["id"])

    blocked = delete_task(client, headers, task_id)

    assert started.status_code == 202
    task = client.get("/tasks", headers=headers).json()["items"][0]
    assert task["can_delete"] is False
    assert "发布任务" in task["delete_disabled_reason"]
    assert blocked.status_code == 409
    assert "发布任务" in blocked.json()["detail"]
    assert dispatcher.blog.submissions == []
    assert client.get(f"/tasks/{task_id}/current-version", headers=headers).status_code == 200


def test_terminal_publication_evidence_remains_listed_after_task_deletion(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = publication_client(tmp_path)
    task_id, revision = saved_article(client, headers, dispatcher)
    started = publish(client, headers, task_id=task_id, revision_id=revision["id"])
    dispatcher.run_all()

    assert delete_task(client, headers, task_id).status_code == 204

    stored = client.get(f"/publication/publish-tasks/{started.json()['id']}", headers=headers)
    listed = client.get("/publication/publish-tasks", headers=headers)
    assert stored.status_code == 200
    assert stored.json()["title"] == revision["title"]
    assert stored.json()["preview_url"] is not None
    assert [attempt["attempt"] for attempt in stored.json()["attempts"]] == [1]
    assert [item["id"] for item in listed.json()["items"]] == [started.json()["id"]]
    assert client.get("/publication/eligible-articles", headers=headers).json()["items"] == []


def test_deleting_a_task_invalidates_queued_zhiyan_work(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, ["Unfinished"])

    assert delete_task(client, headers, task_id).status_code == 204
    dispatcher.run_all()

    assert dispatcher.provider.requests == []
    assert client.get(f"/tasks/{task_id}/zhiyan", headers=headers).status_code == 404


def test_a_zhiyan_run_committed_after_deletion_is_rejected_by_the_worker(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, revision_ids = confirm_sources(client, headers, ["Raced"])
    execution_id = dispatcher.execution_ids[0]
    assert delete_task(client, headers, task_id).status_code == 204

    # Recreate the only dangerous serialization: a start transaction that read
    # the active task before deletion and committed its queued run afterward.
    database = Database(dispatcher.database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        execution = session.get(Execution, execution_id)
        assert execution is not None
        execution.status = "queued"
        execution.cancellation_requested_at = None
        execution.error_code = None
        execution.error_message = None
        execution.finished_at = None
        session.commit()
    database.dispose()

    dispatcher.run_all()

    assert dispatcher.provider.requests == []
    database = Database(dispatcher.database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        assert (
            session.scalar(
                select(ZhiyanReport).where(ZhiyanReport.source_revision_id == UUID(revision_ids[0]))
            )
            is None
        )
    database.dispose()


def test_late_zhiyan_and_liyan_results_cannot_mutate_a_deleted_task(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    zhiyan_task_id, revision_ids = confirm_sources(client, headers, ["Late zhiyan"])

    def late_zhiyan(_: ZhiyanRequest) -> ZhiyanProviderResult:
        assert delete_task(client, headers, zhiyan_task_id).status_code == 204
        return accepted_result("迟到的知言结果")

    monkeypatch.setattr(dispatcher.provider, "analyze", late_zhiyan)
    zhiyan_execution_id = dispatcher.execution_ids[0]
    dispatcher.run_next()

    liyan_task_id, _ = confirm_sources(
        client,
        headers,
        ["Late liyan"],
        idempotency_key="late-liyan-task",
        client_session_id="late-liyan-session",
    )
    monkeypatch.undo()
    dispatcher.run_all()
    started = client.post(
        f"/tasks/{liyan_task_id}/liyan-runs",
        headers=headers,
        json={
            "idempotency_key": "late-liyan-run",
            "instruction": {"content": [{"type": "text", "text": "写成文章"}]},
        },
    )
    assert started.status_code == 202, started.text

    def late_liyan(_: LiyanRequest) -> LiyanProviderResult:
        assert delete_task(client, headers, liyan_task_id).status_code == 204
        return LiyanProviderResult(
            article_text='{"title":"迟到文章","body_markdown":"不得写回"}',
            model="deepseek-v4-flash",
            response_id="late_liyan",
        )

    monkeypatch.setattr(dispatcher.liyan_provider, "generate", late_liyan)
    liyan_execution_id = dispatcher.execution_ids[0]
    dispatcher.run_next()

    database = Database(dispatcher.database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        zhiyan_execution = session.get(Execution, zhiyan_execution_id)
        liyan_execution = session.get(Execution, liyan_execution_id)
        assert zhiyan_execution is not None and zhiyan_execution.status == "cancelled"
        assert liyan_execution is not None and liyan_execution.status == "cancelled"
        assert "迟到的知言结果" in str(zhiyan_execution.stale_result)
        assert "迟到文章" in str(liyan_execution.stale_result)
        assert (
            session.scalar(
                select(ZhiyanReport).where(ZhiyanReport.source_revision_id == UUID(revision_ids[0]))
            )
            is None
        )
        assert (
            session.scalar(
                select(LiyanRunResult).where(LiyanRunResult.execution_id == liyan_execution_id)
            )
            is None
        )
    database.dispose()


def test_one_user_cannot_delete_another_users_task_or_read_retained_publication(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = publication_client(tmp_path)
    task_id, revision = saved_article(client, headers, dispatcher)
    started = publish(client, headers, task_id=task_id, revision_id=revision["id"])
    dispatcher.run_all()
    intruder = {"Authorization": "Bearer second-token"}

    assert delete_task(client, intruder, task_id).status_code == 404
    retained = client.get(f"/publication/publish-tasks/{started.json()['id']}", headers=intruder)
    assert retained.status_code == 404
    assert client.get("/publication/publish-tasks", headers=intruder).json()["items"] == []
