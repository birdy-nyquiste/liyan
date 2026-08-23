from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.orm import Session
from zhiyan_support import DeterministicLiyanProvider, confirm_sources, zhiyan_client

from liyan_server.database import Database, Execution, Task, ZhiyanReport
from liyan_server.liyan.acceptance import accept_article_text
from liyan_server.liyan.failures import LiyanRunFailure
from liyan_server.liyan.provider import (
    LiyanProviderFailure,
    LiyanProviderResult,
    LiyanRequest,
)
from liyan_server.liyan.worker import process_liyan_run

SOURCES = ["四天工作制已经没有争议", "小企业为什么害怕四天工作制"]


def _current_capsule(session: Session, task_id: str, item_id: str = "F-01") -> dict[str, str]:
    task = session.get(Task, UUID(task_id))
    assert task is not None and task.current_version_id is not None
    report = session.query(ZhiyanReport).filter_by(owner_id=task.owner_id).first()
    assert report is not None
    return {
        "type": "capsule",
        "task_version_id": str(task.current_version_id),
        "report_id": str(report.id),
        "item_id": item_id,
    }


def test_capsules_resolve_at_their_instruction_position_without_implying_agreement(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, SOURCES[:1])
    dispatcher.run_all()
    database = Database(dispatcher.database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        capsule = _current_capsule(session, task_id)
    database.dispose()

    started = client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={
            "idempotency_key": "capsule-context",
            "instruction": {
                "content": [
                    {"type": "text", "text": "挑战"},
                    capsule,
                    {"type": "text", "text": "，并改写为更严谨的判断。"},
                ]
            },
        },
    )

    assert started.status_code == 202
    dispatcher.run_all()
    request = dispatcher.liyan_provider.requests[-1]
    assert '"text": "挑战"' in request.input_text
    assert '"capsule": 1' in request.input_text
    assert '"text": "，并改写为更严谨的判断。"' in request.input_text
    assert "英国试验中的所有企业营收均增长 35%。" in request.input_text
    assert "选择胶囊不表示同意" in request.instructions


def test_capsules_reject_stale_missing_and_forged_report_items(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, SOURCES[:1])
    dispatcher.run_all()
    database = Database(dispatcher.database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        valid = _current_capsule(session, task_id)
    database.dispose()

    invalid_capsules = [
        {**valid, "task_version_id": "00000000-0000-0000-0000-000000000001"},
        {**valid, "report_id": "00000000-0000-0000-0000-000000000002"},
        {**valid, "item_id": "F-99"},
    ]
    for index, capsule in enumerate(invalid_capsules):
        response = client.post(
            f"/tasks/{task_id}/liyan-runs",
            headers=headers,
            json={
                "idempotency_key": f"invalid-capsule-{index}",
                "instruction": {"content": [capsule]},
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "立言指令包含无效或过期的知言引用。"


def test_duplicate_capsule_identity_is_rejected_even_for_a_direct_client(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, SOURCES[:1])
    dispatcher.run_all()
    database = Database(dispatcher.database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        capsule = _current_capsule(session, task_id)
    database.dispose()

    response = client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={
            "idempotency_key": "duplicate-capsule",
            "instruction": {"content": [capsule, capsule]},
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "立言指令包含重复的知言引用。"


@pytest.mark.parametrize("identifier", ["E-01", "capsule: 1"])
def test_generated_article_rejects_internal_identifiers(identifier: str) -> None:
    with pytest.raises(LiyanRunFailure):
        accept_article_text(
            f'{{"title":"初稿","body_markdown":"依据 {identifier} 展开论述。"}}'
        )


def test_generation_waits_for_every_current_zhiyan_report(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, SOURCES)

    blocked = client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={"idempotency_key": "liyan-1", "instruction": "", "working_copy": None},
    )

    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "全部知言报告成功后才能生成立言。"

    dispatcher.run_all()
    started = client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={"idempotency_key": "liyan-1", "instruction": "", "working_copy": None},
    )

    assert started.status_code == 202
    assert started.json()["status"] == "running"
    assert started.json()["capabilities"]["can_cancel"] is True


def test_a_successful_run_receives_context_in_order_and_remains_retrievable(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, SOURCES)
    dispatcher.run_all()

    started = client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={
            "idempotency_key": "liyan-with-copy",
            "instruction": "保留开头，语气克制。",
            "working_copy": {
                "title": "旧标题",
                "body_markdown": "这是已有开头。",
            },
        },
    )
    assert started.status_code == 202
    dispatcher.run_all()

    recovered = client.get(f"/tasks/{task_id}/liyan", headers=headers)
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "succeeded"
    assert recovered.json()["result"]["title"] == "四天工作制真正考验的是什么"
    assert recovered.json()["result"]["body_markdown"].startswith("工时只是生产方式的一部分。")

    request = dispatcher.liyan_provider.requests[-1]
    assert request.instructions
    assert request.input_text.index("<CURRENT_SOURCES_AND_REPORTS>") < request.input_text.index(
        "<CURRENT_WORKING_COPY>"
    )
    assert request.input_text.index("<CURRENT_WORKING_COPY>") < request.input_text.index(
        "<RESOLVED_INSTRUCTION_CONTEXT>"
    )
    assert request.input_text.index("<RESOLVED_INSTRUCTION_CONTEXT>") < request.input_text.index(
        "<USER_INSTRUCTION>"
    )
    assert "四天工作制已经没有争议" in request.input_text
    assert "旧标题" in request.input_text
    assert request.input_text.endswith(
        '<USER_INSTRUCTION>\n{"content": [{"text": "保留开头，语气克制。", '
        '"type": "text"}]}\n</USER_INSTRUCTION>'
    )


def test_empty_instruction_stays_empty_and_the_same_operation_is_idempotent(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, SOURCES[:1])
    dispatcher.run_all()

    first = client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={"idempotency_key": "same-run", "instruction": "", "working_copy": None},
    )
    replay = client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={"idempotency_key": "same-run", "instruction": "", "working_copy": None},
    )

    assert first.status_code == replay.status_code == 202
    assert first.json()["execution"]["id"] == replay.json()["execution"]["id"]
    assert len(dispatcher.execution_ids) == 1
    dispatcher.run_all()
    request = dispatcher.liyan_provider.requests[-1]
    assert request.input_text.endswith(
        '<USER_INSTRUCTION>\n{"content": []}\n</USER_INSTRUCTION>'
    )
    assert "<CURRENT_WORKING_COPY>" not in request.input_text


def test_the_initial_operation_recovers_once_and_rejects_forbidden_output(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, SOURCES[:1])
    dispatcher.run_all()
    dispatcher.liyan_provider.outcomes.append(
        LiyanProviderResult(
            article_text='{"title":"初稿","body_markdown":"采用胶囊 1，结论如下。"}',
            model="deepseek-v4-flash",
        )
    )

    client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={"idempotency_key": "recover-once", "instruction": "直接表达。"},
    )
    dispatcher.run_all()

    state = client.get(f"/tasks/{task_id}/liyan", headers=headers).json()
    assert len(dispatcher.liyan_provider.requests) == 2
    assert state["status"] == "succeeded"
    assert "胶囊" not in state["result"]["body_markdown"]


def test_output_arriving_after_cancellation_never_becomes_a_working_copy(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, SOURCES[:1])
    dispatcher.run_all()
    started = client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={"idempotency_key": "cancel-race", "instruction": "写一篇评论。"},
    ).json()
    execution_id = started["execution"]["id"]
    dispatcher.execution_ids.clear()

    class CancellingProvider(DeterministicLiyanProvider):
        def generate(self, request: LiyanRequest) -> LiyanProviderResult:
            cancelled = client.post(f"/executions/{execution_id}/cancel", headers=headers)
            assert cancelled.status_code == 202
            return LiyanProviderResult(
                article_text='{"title":"迟到文章","body_markdown":"这份内容不得进入草稿。"}',
                model="deepseek-v4-flash",
            )

    process_liyan_run(
        dispatcher.database_url,
        UUID(execution_id),
        CancellingProvider(),
        dispatcher,
    )

    state = client.get(f"/tasks/{task_id}/liyan", headers=headers).json()
    assert state["status"] == "cancelled"
    assert state["result"] is None
    assert state["capabilities"]["can_generate"] is True


def test_an_active_liyan_run_blocks_conflicting_source_work(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, SOURCES[:1])
    dispatcher.run_all()
    client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={"idempotency_key": "active-run", "instruction": ""},
    )

    blocked = client.post(f"/tasks/{task_id}/source-edit-sessions", headers=headers)

    assert blocked.status_code == 409


def test_manual_retries_are_bounded_by_server_owned_timing(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, SOURCES[:1])
    dispatcher.run_all()
    request = {
        "instruction": {"content": [{"type": "text", "text": "写一篇短评。"}]},
        "working_copy": None,
    }
    dispatcher.liyan_provider.outcomes.extend(
        [
            LiyanProviderFailure("provider_unavailable", "暂时不可用"),
            LiyanProviderFailure("provider_unavailable", "暂时不可用"),
        ]
    )
    client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={"idempotency_key": "initial-failure", **request},
    )
    dispatcher.run_all()

    for index in range(2):
        state = client.get(f"/tasks/{task_id}/liyan", headers=headers).json()
        assert state["request"] == {
            "instruction": request["instruction"],
            "working_copy": None,
        }
        _elapse_backoff(dispatcher.database_url, state["execution"]["id"])
        retried = client.post(
            f"/tasks/{task_id}/liyan-runs",
            headers=headers,
            json={"idempotency_key": f"manual-{index}", **state["request"]},
        )
        assert retried.status_code == 202
        dispatcher.liyan_provider.outcomes.append(
            LiyanProviderFailure("provider_unavailable", "暂时不可用")
        )
        dispatcher.run_all()

    state = client.get(f"/tasks/{task_id}/liyan", headers=headers).json()
    _elapse_backoff(dispatcher.database_url, state["execution"]["id"])
    refused = client.post(
        f"/tasks/{task_id}/liyan-runs",
        headers=headers,
        json={"idempotency_key": "manual-3", **request},
    )

    assert refused.status_code == 429
    state = client.get(f"/tasks/{task_id}/liyan", headers=headers).json()
    assert state["capabilities"]["retry"]["remaining"] == 0
    assert state["capabilities"]["retry"]["allowed_at"] is not None


def _elapse_backoff(database_url: str, execution_id: str) -> None:
    database = Database(database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        execution = session.get(Execution, UUID(execution_id))
        assert execution is not None
        execution.retry_allowed_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    database.dispose()
