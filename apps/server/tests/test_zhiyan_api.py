"""One trustworthy 知言报告 for one accepted source Revision.

The formal task's confirmation already queues the initial run, so these tests
start from a queued run rather than starting one themselves; how many runs a
target may have and when belongs to test_zhiyan_orchestration.
"""

import json
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from zhiyan_support import (
    OPENED_URL,
    RecordingDispatcher,
    confirm_single_source,
    elapse_retry_backoff,
    latest_stored_run,
    report_document,
    unavailable,
    zhiyan_client,
)

from liyan_server.database import Database, Execution
from liyan_server.zhiyan.provider import SearchAction, ZhiyanProviderFailure, ZhiyanProviderResult


def confirmed_task(tmp_path: Path) -> tuple[TestClient, dict[str, str], RecordingDispatcher, str]:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    return client, headers, dispatcher, confirm_single_source(client, headers)


def fail_twice(dispatcher: RecordingDispatcher, failure: ZhiyanProviderFailure) -> None:
    """Exhaust the initial operation's two runs with the same failure."""
    dispatcher.provider.outcomes.extend([failure, failure])


def test_a_queued_run_receives_only_the_accepted_revision_and_server_owned_policy(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, revision_id = confirmed_task(tmp_path)

    queued = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()
    dispatcher.run_next()

    assert queued["status"] == "running"
    assert queued["execution"]["operation"] == "analyze_source"
    assert queued["capabilities"]["can_start"] is False
    assert queued["capabilities"]["can_cancel"] is True
    request = dispatcher.provider.requests[0]
    assert request.model == "deepseek-v4-flash"
    assert request.prompt_version
    assert "<source-content>" in request.input_text
    assert revision_id in request.input_text
    assert "四天工作制" in request.input_text
    assert "instructions" not in request.input_text
    assert request.tool_policy.web_search_enabled is True


def test_a_successful_run_yields_the_seven_sections_and_stable_references(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, revision_id = confirmed_task(tmp_path)
    dispatcher.run_next()

    state = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()

    assert state["status"] == "succeeded"
    assert state["execution"]["status"] == "succeeded"
    assert state["execution"]["result_id"] == state["report"]["id"]
    document = state["report"]["document"]
    assert set(document) == {
        "overview",
        "source",
        "facts",
        "viewpoints",
        "logic",
        "intent",
        "evidence",
    }
    assert document["facts"]["items"][0]["evidence_ids"] == ["E-01"]
    assert document["facts"]["items"][0]["quote"].startswith("所有企业")
    assert document["facts"]["items"][0]["verdict"] == "部分准确"
    assert document["logic"]["argument_chain"].startswith("试验出现积极结果")
    assert document["intent"]["target_audience"] == "关心劳动政策的公众和决策者。"
    assert document["overview"]["key_findings"] == [
        {"ref_id": "F-01", "text": "35% 不代表所有企业。"}
    ]
    assert document["evidence"]["items"][0]["id"] == "E-01"
    assert document["viewpoints"]["items"] == []
    assert document["viewpoints"]["empty_state"] == "来源中没有可归属的观点表达。"
    assert state["report"]["prompt_version"]
    assert state["report"]["model"] == "deepseek-v4-flash"


def test_a_successful_report_cannot_be_regenerated(tmp_path: Path) -> None:
    client, headers, dispatcher, revision_id = confirmed_task(tmp_path)
    dispatcher.run_next()

    again = client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)

    assert again.status_code == 409
    state = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()
    assert state["capabilities"]["can_start"] is False
    assert state["capabilities"]["can_cancel"] is False


def test_a_second_run_starting_before_the_first_ends_is_rejected(tmp_path: Path) -> None:
    client, headers, _, revision_id = confirmed_task(tmp_path)

    again = client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)

    assert again.status_code == 409


def test_a_provider_failure_leaves_the_revision_without_a_report(tmp_path: Path) -> None:
    client, headers, dispatcher, revision_id = confirmed_task(tmp_path)
    fail_twice(
        dispatcher,
        ZhiyanProviderFailure(
            "provider_unavailable",
            "分析服务暂时不可用，请稍后重试。",
            internal_error="secret key sk-live-1",
        ),
    )
    dispatcher.run_all()

    state = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()

    assert state["status"] == "failed"
    assert state["report"] is None
    assert "sk-live-1" not in json.dumps(state, ensure_ascii=False)


def test_a_user_is_told_the_same_thing_however_a_run_failed(tmp_path: Path) -> None:
    """Function Spec §5.4: the real reason stays with the operator, not the user."""
    client, headers, dispatcher, revision_id = confirmed_task(tmp_path)
    fail_twice(
        dispatcher,
        ZhiyanProviderFailure(
            "provider_unavailable",
            "分析服务暂时不可用，请稍后重试。",
            internal_error="secret key sk-live-1",
        ),
    )
    dispatcher.run_all()

    state = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()

    assert state["execution"]["error"] == {"code": "busy", "message": "服务繁忙，请重试。"}
    recorded = latest_stored_run(dispatcher.database_url, revision_id)
    assert recorded.error_code == "provider_unavailable"
    assert recorded.internal_error is not None
    assert "sk-live-1" in recorded.internal_error


def test_an_invalid_provider_report_is_rejected_deterministically(tmp_path: Path) -> None:
    client, headers, dispatcher, revision_id = confirmed_task(tmp_path)
    invalid = report_document()
    invalid["facts"]["items"][0]["evidence_ids"] = []
    rejected = ZhiyanProviderResult(
        report_text=json.dumps(invalid, ensure_ascii=False),
        search_actions=(SearchAction(kind="open_page", url=OPENED_URL),),
        model="deepseek-v4-flash",
    )
    dispatcher.provider.outcomes.extend([rejected, rejected])
    dispatcher.run_all()

    state = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()

    assert state["status"] == "failed"
    assert latest_stored_run(dispatcher.database_url, revision_id).error_code == (
        "unsupported_fact_verdict"
    )


def test_evidence_the_provider_never_opened_is_rejected(tmp_path: Path) -> None:
    client, headers, dispatcher, revision_id = confirmed_task(tmp_path)
    unopened = ZhiyanProviderResult(
        report_text=json.dumps(report_document(), ensure_ascii=False),
        search_actions=(SearchAction(kind="search", query="四天工作制"),),
        model="deepseek-v4-flash",
    )
    dispatcher.provider.outcomes.extend([unopened, unopened])
    dispatcher.run_all()

    state = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()

    assert state["status"] == "failed"
    assert latest_stored_run(dispatcher.database_url, revision_id).error_code == (
        "unopened_evidence"
    )


def test_a_manual_retry_after_failure_can_still_produce_the_report(tmp_path: Path) -> None:
    client, headers, dispatcher, revision_id = confirmed_task(tmp_path)
    fail_twice(dispatcher, unavailable())
    dispatcher.run_all()
    elapse_retry_backoff(dispatcher.database_url, revision_id)

    retried = client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)
    dispatcher.run_next()

    assert retried.status_code == 202
    assert retried.json()["execution"]["attempt"] == 3
    state = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()
    assert state["status"] == "succeeded"


def test_a_cancelled_run_cannot_become_a_report(tmp_path: Path) -> None:
    client, headers, dispatcher, revision_id = confirmed_task(tmp_path)
    started = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()
    execution_id = started["execution"]["id"]

    cancelled = client.post(f"/executions/{execution_id}/cancel", headers=headers)
    dispatcher.run_next()

    assert cancelled.status_code == 202
    state = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()
    assert state["status"] == "cancelled"
    assert state["report"] is None
    assert state["capabilities"]["can_cancel"] is False
    assert client.get(f"/executions/{execution_id}", headers=headers).json()["status"] == (
        "cancelled"
    )


def test_a_redelivered_queue_message_cannot_rerun_a_finished_run(tmp_path: Path) -> None:
    """Only a queued run may be claimed, so a duplicate message asks nothing twice."""
    client, headers, dispatcher, revision_id = confirmed_task(tmp_path)
    dispatcher.run_next()
    accepted = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()
    succeeded_run = accepted["execution"]["id"]

    dispatcher.execution_ids.append(UUID(succeeded_run))
    dispatcher.run_next()

    assert len(dispatcher.provider.requests) == 1
    unchanged = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()
    assert unchanged["report"] == accepted["report"]


def test_another_user_cannot_read_or_start_a_run(tmp_path: Path) -> None:
    client, headers, dispatcher, revision_id = confirmed_task(tmp_path)
    dispatcher.run_next()
    intruder = {"Authorization": "Bearer second-token"}

    assert client.get(f"/source-revisions/{revision_id}/zhiyan", headers=intruder).status_code == (
        404
    )
    assert client.post(
        f"/source-revisions/{revision_id}/zhiyan-runs", headers=intruder
    ).status_code == 404


def test_a_second_active_run_cannot_be_inserted_even_without_a_prior_read(
    tmp_path: Path,
) -> None:
    """One active 知言 run per source Revision is enforced by the database, not a read."""
    _, _, dispatcher, _ = confirmed_task(tmp_path)
    queued = dispatcher.execution_ids[0]

    database = Database(dispatcher.database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        original = session.get(Execution, queued)
        assert original is not None
        session.add(
            Execution(
                owner_id=original.owner_id,
                operation=original.operation,
                target_type=original.target_type,
                target_id=original.target_id,
                input_version=original.input_version,
                input_identity=original.input_identity,
                input_snapshot=original.input_snapshot,
                attempt=original.attempt + 1,
                origin="manual",
                status="queued",
                created_at=original.created_at,
            )
        )
        try:
            session.commit()
        except IntegrityError:
            pass
        else:
            raise AssertionError("A second active 知言 run must be rejected by the database.")
    database.dispose()


def test_the_current_version_exposes_its_source_revisions(tmp_path: Path) -> None:
    client, headers, _, revision_id = confirmed_task(tmp_path)
    task_id = client.get("/tasks", headers=headers).json()["items"][0]["id"]

    version = client.get(f"/tasks/{task_id}/current-version", headers=headers).json()

    assert version["number"] == 1
    assert [source["id"] for source in version["source_revisions"]] == [revision_id]
    assert version["source_revisions"][0]["title"] == "四天工作制已经没有争议"
