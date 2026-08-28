"""知言 across one complete 任务版本.

A 任务版本 holds one to three source Revisions, and each gets its own run. These
tests cover what only becomes visible at that scale: what confirmation queues,
how partial progress and partial failure read, how far recovery goes on its own,
what a manual retry costs, and what cancellation guarantees.
"""

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from database_support import migrated_database
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from zhiyan_support import (
    DEFAULT_SUMMARY,
    DeterministicJwtVerifier,
    DeterministicZhiyanProvider,
    RecordingDispatcher,
    abandon_run,
    accepted_result,
    confirm_session,
    confirm_sources,
    create_session_sources,
    elapse_retry_backoff,
    source_body,
    unavailable,
    zhiyan_client,
)

from liyan_server.app import create_app
from liyan_server.database import Database, Execution
from liyan_server.settings import Settings
from liyan_server.zhiyan.provider import (
    SearchAction,
    ZhiyanProviderFailure,
    ZhiyanProviderResult,
    ZhiyanRequest,
)
from liyan_server.zhiyan.recovery import MANUAL_RETRY_LIMIT
from liyan_server.zhiyan.runs import ZHIYAN_OPERATION
from liyan_server.zhiyan.worker import process_zhiyan_run

THREE_SOURCES = ["四天工作制已经没有争议", "碳中和的真实成本", "远程办公的生产力争论"]


def runs_for(database_url: str, source_revision_id: str) -> list[Execution]:
    database = Database(database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        runs = list(
            session.scalars(
                select(Execution)
                .where(
                    Execution.target_id == UUID(source_revision_id),
                    Execution.operation == ZHIYAN_OPERATION,
                )
                .order_by(Execution.attempt)
            ).all()
        )
    database.dispose()
    return runs


def source_state(
    client: TestClient,
    headers: dict[str, str],
    task_id: str,
    index: int,
) -> dict[str, Any]:
    overview = client.get(f"/tasks/{task_id}/zhiyan", headers=headers)
    assert overview.status_code == 200, overview.text
    return dict(overview.json()["sources"][index])


def fail_initial_operation(dispatcher: RecordingDispatcher, revision_id: str) -> None:
    """Burn both runs of one Revision's initial operation, then let time pass."""
    dispatcher.provider.outcomes.extend([unavailable(), unavailable()])
    dispatcher.run_all()
    elapse_retry_backoff(dispatcher.database_url, revision_id)


def test_confirmation_queues_one_run_for_each_source(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)

    task_id, revision_ids = confirm_sources(client, headers, THREE_SOURCES)

    assert len(dispatcher.execution_ids) == 3
    overview = client.get(f"/tasks/{task_id}/zhiyan", headers=headers).json()
    assert [source["source_revision_id"] for source in overview["sources"]] == revision_ids
    assert [source["status"] for source in overview["sources"]] == ["running"] * 3
    for revision_id in revision_ids:
        runs = runs_for(dispatcher.database_url, revision_id)
        assert [run.origin for run in runs] == ["initial"]
        assert [run.attempt for run in runs] == [1]


def test_a_repeated_confirmation_queues_no_second_run_for_the_same_source(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    source_ids = create_session_sources(client, headers, THREE_SOURCES)
    confirmed = confirm_session(client, headers, source_ids)

    replayed = confirm_session(client, headers, source_ids)

    assert replayed == confirmed
    assert len(dispatcher.execution_ids) == 3


def test_a_queue_that_refuses_the_run_still_leaves_the_formal_task_created(
    tmp_path: Path,
) -> None:
    """Function Spec §2.1: a 知言 failure never rolls back the task just created."""

    class RefusingDispatcher:
        def dispatch(self, execution_id: UUID, operation: str) -> None:
            raise RuntimeError("The broker is unreachable.")

        def is_reachable(self) -> bool:
            return False

    database_url = migrated_database(tmp_path)
    client = TestClient(
        create_app(
            Settings(database_url=database_url, allowed_emails="writer@example.com"),
            jwt_verifier=DeterministicJwtVerifier(),
            execution_dispatcher=RefusingDispatcher(),
        )
    )
    headers = {"Authorization": "Bearer allowed-token"}

    task_id, revision_ids = confirm_sources(client, headers, THREE_SOURCES[:1])

    assert client.get("/tasks", headers=headers).json()["items"][0]["id"] == task_id
    state = source_state(client, headers, task_id, 0)
    assert state["status"] == "failed"
    assert state["execution"]["error"] == {"code": "busy", "message": "服务繁忙，请重试。"}
    assert state["capabilities"]["can_start"] is True
    runs = runs_for(database_url, revision_ids[0])
    assert [run.error_code for run in runs] == ["dispatch_failed"]


def test_sources_progress_independently_of_each_other(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, THREE_SOURCES)

    second = dispatcher.execution_ids.pop(1)
    process_zhiyan_run(dispatcher.database_url, second, dispatcher.provider, dispatcher)

    statuses = [
        source_state(client, headers, task_id, index)["status"] for index in range(3)
    ]
    assert statuses == ["running", "succeeded", "running"]


def test_one_failed_source_leaves_the_other_reports_readable(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, THREE_SOURCES)
    # The middle source fails both runs of its initial operation; the others succeed.
    dispatcher.provider.outcomes.extend(
        [accepted_result(), unavailable(), accepted_result(), unavailable()]
    )
    dispatcher.run_all()

    overview = client.get(f"/tasks/{task_id}/zhiyan", headers=headers).json()

    assert [source["status"] for source in overview["sources"]] == [
        "succeeded",
        "failed",
        "succeeded",
    ]
    assert overview["sources"][0]["report"]["document"]["overview"]["content_summary"]
    assert overview["sources"][2]["report"]["document"]["overview"]["content_summary"]
    assert overview["liyan"]["can_generate"] is False
    assert overview["liyan"]["unavailable_reason"]


def test_liyan_stays_shut_while_any_report_is_still_running(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, THREE_SOURCES)

    dispatcher.run_next()
    waiting = client.get(f"/tasks/{task_id}/zhiyan", headers=headers).json()
    dispatcher.run_all()
    complete = client.get(f"/tasks/{task_id}/zhiyan", headers=headers).json()

    assert waiting["liyan"] == {
        "can_generate": False,
        "unavailable_reason": "知言分析尚未全部完成，全部报告成功后才能生成立言。",
    }
    assert complete["liyan"] == {"can_generate": True, "unavailable_reason": None}


def test_the_initial_operation_recovers_once_on_its_own(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, revision_ids = confirm_sources(client, headers, THREE_SOURCES[:1])
    dispatcher.provider.outcomes.append(unavailable())

    dispatcher.run_next()
    after_first_failure = source_state(client, headers, task_id, 0)
    dispatcher.run_all()

    assert after_first_failure["status"] == "running"
    assert [run.origin for run in runs_for(dispatcher.database_url, revision_ids[0])] == [
        "initial",
        "automatic",
    ]
    assert source_state(client, headers, task_id, 0)["status"] == "succeeded"


def test_the_initial_operation_stops_after_its_second_run(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, revision_ids = confirm_sources(client, headers, THREE_SOURCES[:1])
    dispatcher.provider.outcomes.extend([unavailable(), unavailable()])

    dispatcher.run_all()

    assert dispatcher.execution_ids == []
    assert len(runs_for(dispatcher.database_url, revision_ids[0])) == 2
    assert source_state(client, headers, task_id, 0)["status"] == "failed"


def test_a_failure_no_rerun_could_survive_does_not_spend_the_automatic_attempt(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, revision_ids = confirm_sources(client, headers, THREE_SOURCES[:1])
    dispatcher.provider.outcomes.append(
        ZhiyanProviderFailure("provider_unconfigured", "知言服务暂时不可用，请稍后重试。")
    )

    dispatcher.run_all()

    assert len(runs_for(dispatcher.database_url, revision_ids[0])) == 1
    state = source_state(client, headers, task_id, 0)
    assert state["status"] == "failed"
    assert state["capabilities"]["can_start"] is True


def test_a_pending_backoff_withholds_the_retry_and_names_its_moment(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, revision_ids = confirm_sources(client, headers, THREE_SOURCES[:1])
    dispatcher.provider.outcomes.extend([unavailable(), unavailable()])
    dispatcher.run_all()

    state = source_state(client, headers, task_id, 0)
    refused = client.post(
        f"/source-revisions/{revision_ids[0]}/zhiyan-runs",
        headers=headers,
    )

    assert state["capabilities"]["can_start"] is False
    assert state["capabilities"]["retry"]["allowed"] is False
    assert state["capabilities"]["retry"]["allowed_at"] is not None
    assert state["capabilities"]["retry"]["remaining"] == MANUAL_RETRY_LIMIT
    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) > 0


def test_each_manual_retry_creates_exactly_one_run(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    _, revision_ids = confirm_sources(client, headers, THREE_SOURCES[:1])
    revision_id = revision_ids[0]
    fail_initial_operation(dispatcher, revision_id)

    retried = client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)

    assert retried.status_code == 202
    assert len(dispatcher.execution_ids) == 1
    runs = runs_for(dispatcher.database_url, revision_id)
    assert [run.origin for run in runs] == ["initial", "automatic", "manual"]
    assert retried.json()["capabilities"]["retry"]["remaining"] == MANUAL_RETRY_LIMIT - 1


def test_a_manual_retry_never_recovers_by_itself(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    _, revision_ids = confirm_sources(client, headers, THREE_SOURCES[:1])
    revision_id = revision_ids[0]
    fail_initial_operation(dispatcher, revision_id)
    client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)

    dispatcher.provider.outcomes.append(unavailable())
    dispatcher.run_all()

    assert [
        run.origin for run in runs_for(dispatcher.database_url, revision_id)
    ] == ["initial", "automatic", "manual"]


def test_the_third_manual_retry_in_the_window_is_refused_with_server_timing(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, revision_ids = confirm_sources(client, headers, THREE_SOURCES[:1])
    revision_id = revision_ids[0]
    fail_initial_operation(dispatcher, revision_id)
    for _ in range(MANUAL_RETRY_LIMIT):
        assert (
            client.post(
                f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers
            ).status_code
            == 202
        )
        dispatcher.provider.outcomes.append(unavailable())
        dispatcher.run_all()
        elapse_retry_backoff(dispatcher.database_url, revision_id)

    refused = client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)

    assert refused.status_code == 429
    state = source_state(client, headers, task_id, 0)
    assert state["capabilities"]["can_start"] is False
    assert state["capabilities"]["retry"] == {
        "allowed": False,
        "remaining": 0,
        "allowed_at": state["capabilities"]["retry"]["allowed_at"],
    }
    assert state["capabilities"]["retry"]["allowed_at"] is not None


def test_a_cancelled_run_does_not_spend_the_automatic_attempt(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, revision_ids = confirm_sources(client, headers, THREE_SOURCES[:1])
    execution_id = source_state(client, headers, task_id, 0)["execution"]["id"]

    client.post(f"/executions/{execution_id}/cancel", headers=headers)
    dispatcher.run_all()

    assert len(runs_for(dispatcher.database_url, revision_ids[0])) == 1
    state = source_state(client, headers, task_id, 0)
    assert state["status"] == "cancelled"
    assert state["execution"]["error"]["code"] == "cancelled"
    assert state["capabilities"]["can_start"] is True
    assert state["capabilities"]["retry"]["allowed"] is True


def test_output_arriving_after_an_accepted_cancellation_is_kept_only_for_tracing(
    tmp_path: Path,
) -> None:
    """The run is already claimed, so cancellation and the provider's answer race."""
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, revision_ids = confirm_sources(client, headers, THREE_SOURCES[:1])
    execution_id = source_state(client, headers, task_id, 0)["execution"]["id"]

    class CancellingProvider(DeterministicZhiyanProvider):
        def analyze(self, request: ZhiyanRequest) -> object:  # type: ignore[override]
            cancelled = client.post(f"/executions/{execution_id}/cancel", headers=headers)
            assert cancelled.status_code == 202
            assert cancelled.json()["status"] == "cancel_requested"
            return accepted_result()

    process_zhiyan_run(
        dispatcher.database_url,
        UUID(execution_id),
        CancellingProvider(),  # type: ignore[arg-type]
        dispatcher,
    )

    state = source_state(client, headers, task_id, 0)
    assert state["status"] == "cancelled"
    assert state["report"] is None
    assert client.get(f"/executions/{execution_id}", headers=headers).json()["status"] == (
        "cancelled"
    )
    runs = runs_for(dispatcher.database_url, revision_ids[0])
    assert len(runs) == 1
    # Technical Spec §6.4: the discarded answer stays in the execution record.
    stale = runs[0].stale_result
    assert stale is not None
    assert DEFAULT_SUMMARY in str(stale["report_text"])
    assert stale["response_id"] == "resp_1"
    assert client.get(f"/tasks/{task_id}/zhiyan", headers=headers).json()["liyan"][
        "can_generate"
    ] is False


def test_a_report_arriving_after_another_run_won_is_kept_only_for_tracing(
    tmp_path: Path,
) -> None:
    """An abandoned run keeps working; its answer may never overwrite the report."""
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, revision_ids = confirm_sources(client, headers, THREE_SOURCES[:1])
    revision_id = revision_ids[0]
    abandoned = str(dispatcher.execution_ids[0])

    class OvertakenProvider(DeterministicZhiyanProvider):
        """Loses its run to the timeout sweep, then answers anyway."""

        def analyze(self, request: ZhiyanRequest) -> object:  # type: ignore[override]
            abandon_run(dispatcher.database_url, abandoned)
            assert (
                client.post(
                    f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers
                ).status_code
                == 202
            )
            dispatcher.run_all()
            return accepted_result("迟到的分析结论。")

    process_zhiyan_run(
        dispatcher.database_url,
        UUID(abandoned),
        OvertakenProvider(),  # type: ignore[arg-type]
        dispatcher,
    )

    winner = source_state(client, headers, task_id, 0)
    assert winner["status"] == "succeeded"
    assert winner["report"]["document"]["overview"]["content_summary"] == DEFAULT_SUMMARY
    runs = runs_for(dispatcher.database_url, revision_id)
    assert [run.status for run in runs] == ["stale", "succeeded"]
    assert "迟到的分析结论。" in str(runs[0].stale_result)


def test_another_user_cannot_read_a_task_version_overview(tmp_path: Path) -> None:
    client, headers, _ = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, THREE_SOURCES[:1])

    intruder = client.get(
        f"/tasks/{task_id}/zhiyan",
        headers={"Authorization": "Bearer second-token"},
    )

    assert intruder.status_code == 404


def test_a_source_body_is_never_echoed_into_the_overview(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, THREE_SOURCES[:1])
    dispatcher.run_all()

    overview = client.get(f"/tasks/{task_id}/zhiyan", headers=headers).text

    assert source_body(THREE_SOURCES[0])[:40] not in overview


def test_a_refused_report_is_kept_so_the_refusal_can_be_explained(tmp_path: Path) -> None:
    """Acceptance says which rule the output broke. Only the output says why.

    Three local runs failed `invalid_report_schema` with `JSONDecodeError` at
    character zero, and nothing on the record could say whether the model had
    written prose, an unrecognised fence, or something else — because the text
    was thrown away on this path while cancelled runs kept theirs.
    """
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, ["四天工作制已经没有争议"])

    class WroteProse(DeterministicZhiyanProvider):
        def analyze(self, request: ZhiyanRequest) -> ZhiyanProviderResult:
            return ZhiyanProviderResult(
                report_text="很抱歉，我无法核实这些说法。",
                search_actions=(SearchAction(kind="search", query="四天工作制"),),
                model="deepseek-v4-flash",
                response_id="resp_prose",
            )

    overview = client.get(f"/tasks/{task_id}/zhiyan", headers=headers).json()
    execution_id = overview["sources"][0]["execution"]["id"]
    process_zhiyan_run(
        dispatcher.database_url, UUID(execution_id), WroteProse(), dispatcher
    )

    database = Database(dispatcher.database_url)
    assert database.engine is not None
    try:
        with Session(database.engine) as session:
            execution = session.get(Execution, UUID(execution_id))
            assert execution is not None
            assert execution.error_code == "invalid_report_schema"
            assert execution.stale_result is not None
            assert execution.stale_result["report_text"] == "很抱歉，我无法核实这些说法。"
    finally:
        database.dispose()

    # Kept for tracing, and for nobody else. It quotes 来源 text back, so it
    # reaches an operator through `explain_execution` and never through the API.
    served = client.get(f"/tasks/{task_id}/zhiyan", headers=headers).json()
    assert "stale_result" not in json.dumps(served)
    assert "很抱歉" not in json.dumps(served)
