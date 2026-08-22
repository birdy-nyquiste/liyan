import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from liyan_server.app import create_app
from liyan_server.auth import InvalidAccessToken, VerifiedIdentity
from liyan_server.database import Database, Execution
from liyan_server.settings import Settings
from liyan_server.zhiyan.provider import (
    SearchAction,
    ZhiyanProviderFailure,
    ZhiyanProviderResult,
    ZhiyanRequest,
)
from liyan_server.zhiyan.worker import process_zhiyan_run

OPENED_URL = "https://autonomy.work/four-day-week-pilot"


DEFAULT_SUMMARY = "原文以英国四天工作制试验为依据，呼吁全面强制实施。"


def report_document(summary: str = DEFAULT_SUMMARY) -> dict[str, Any]:
    return {
        "overview": {
            "content_summary": summary,
            "fact_check_summary": "共核查 1 项重要事实：1 项部分准确。",
            "key_findings": [{"ref_id": "F-01", "text": "35% 不代表所有企业。"}],
            "reading_note": "原文引用了真实试验，但改变了指标的适用范围。",
        },
        "source": {
            "genre": "政策评论",
            "provenance": "二手转述",
            "completeness": "完整短文",
            "note": "原文没有提供试验报告链接。",
        },
        "facts": {
            "items": [
                {
                    "id": "F-01",
                    "quote": "所有企业实行四天工作制后，营收都会增长35%。",
                    "claim": "英国试验中的所有企业营收均增长 35%。",
                    "verdict": "部分准确",
                    "explanation": "35% 是提交数据企业相较往年同期的平均变化。",
                    "evidence_ids": ["E-01"],
                }
            ],
            "empty_state": None,
        },
        "viewpoints": {"items": [], "empty_state": "来源中没有可归属的观点表达。"},
        "logic": {
            "argument_chain": "试验出现积极结果 → 政府应全面强制实施。",
            "items": [
                {
                    "id": "L-01",
                    "quote": "数据已经证明四天工作制对所有行业都有效。",
                    "judgment": "结论超出了试验能够支持的范围。",
                    "explanation": "特定参与企业的试验不能证明所有行业获得相同结果。",
                    "related_ids": ["F-01"],
                }
            ],
            "empty_state": None,
        },
        "intent": {
            "explicit_purpose": "支持四天工作制并呼吁政府全面实施。",
            "items": [],
            "target_audience": "关心劳动政策的公众和决策者。",
            "expression_methods": ["使用具体数字增强权威感"],
            "empty_state": "没有可支持的额外意图推断。",
        },
        "evidence": {
            "items": [
                {
                    "id": "E-01",
                    "title": "Autonomy: The UK's Four-Day Week Pilot",
                    "url": OPENED_URL,
                    "explanation": "说明参与企业数量与营收指标的实际统计口径。",
                }
            ],
            "empty_state": None,
        },
    }


class DeterministicJwtVerifier:
    def verify(self, token: str) -> VerifiedIdentity:
        identities = {
            "allowed-token": VerifiedIdentity(
                subject="supabase-user-1", email="writer@example.com"
            ),
            "second-token": VerifiedIdentity(
                subject="supabase-user-2", email="second@example.com"
            ),
        }
        try:
            return identities[token]
        except KeyError as error:
            raise InvalidAccessToken from error


class DeterministicZhiyanProvider:
    def __init__(self) -> None:
        self.outcomes: list[ZhiyanProviderResult | ZhiyanProviderFailure] = []
        self.requests: list[ZhiyanRequest] = []

    def analyze(self, request: ZhiyanRequest) -> ZhiyanProviderResult:
        self.requests.append(request)
        outcome = (
            self.outcomes.pop(0)
            if self.outcomes
            else ZhiyanProviderResult(
                report_text=json.dumps(report_document(), ensure_ascii=False),
                search_actions=(
                    SearchAction(kind="search", query="细颗粒物"),
                    SearchAction(kind="open_page", url=OPENED_URL),
                ),
                model="deepseek-v4-flash",
                response_id="resp_1",
            )
        )
        if isinstance(outcome, ZhiyanProviderFailure):
            raise outcome
        return outcome


class RecordingDispatcher:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.execution_ids: list[UUID] = []
        self.provider = DeterministicZhiyanProvider()

    def dispatch(self, execution_id: UUID) -> None:
        self.execution_ids.append(execution_id)

    def run_next(self) -> None:
        process_zhiyan_run(self.database_url, self.execution_ids.pop(0), self.provider)


def migrated_database(tmp_path: Path) -> str:
    project_root = Path(__file__).resolve().parents[3]
    database_url = f"sqlite+pysqlite:///{tmp_path / 'liyan.db'}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=project_root,
        env=os.environ | {"LIYAN_DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return database_url


def confirmed_task(tmp_path: Path) -> tuple[TestClient, dict[str, str], RecordingDispatcher, str]:
    database_url = migrated_database(tmp_path)
    dispatcher = RecordingDispatcher(database_url)
    client = TestClient(
        create_app(
            Settings(
                database_url=database_url,
                allowed_emails="writer@example.com,second@example.com",
            ),
            jwt_verifier=DeterministicJwtVerifier(),
            execution_dispatcher=dispatcher,
        )
    )
    headers = {"Authorization": "Bearer allowed-token"}
    confirmation = client.post(
        "/task-creation/confirm",
        headers=headers,
        json={
            "idempotency_key": "key-1",
            "source": {
                "title": "四天工作制已经没有争议",
                "body": "英国2022年的四天工作制试验已经证明了显著效果。" * 40,
                "provenance": "https://press.example/story",
            },
        },
    )
    assert confirmation.status_code == 200, confirmation.text
    return client, headers, dispatcher, confirmation.json()["source_revision"]["id"]


def test_a_source_revision_starts_with_no_report(tmp_path: Path) -> None:
    client, headers, _, revision_id = confirmed_task(tmp_path)

    state = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()

    assert state["status"] == "absent"
    assert state["report"] is None
    assert state["execution"] is None
    assert state["capabilities"] == {"can_start": True, "can_cancel": False}


def test_a_run_receives_only_the_accepted_revision_and_server_owned_policy(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, revision_id = confirmed_task(tmp_path)

    started = client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)
    dispatcher.run_next()

    assert started.status_code == 202
    assert started.json()["status"] == "running"
    assert started.json()["execution"]["operation"] == "analyze_source"
    assert started.json()["capabilities"] == {"can_start": False, "can_cancel": True}
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
    client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)
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
    client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)
    dispatcher.run_next()

    again = client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)

    assert again.status_code == 409
    state = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()
    assert state["capabilities"] == {"can_start": False, "can_cancel": False}


def test_a_second_run_starting_before_the_first_ends_is_rejected(tmp_path: Path) -> None:
    client, headers, _, revision_id = confirmed_task(tmp_path)
    client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)

    again = client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)

    assert again.status_code == 409


def test_a_provider_failure_leaves_the_revision_without_a_report(tmp_path: Path) -> None:
    client, headers, dispatcher, revision_id = confirmed_task(tmp_path)
    dispatcher.provider.outcomes.append(
        ZhiyanProviderFailure(
            "provider_unavailable",
            "分析服务暂时不可用，请稍后重试。",
            internal_error="secret key sk-live-1",
        )
    )
    client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)
    dispatcher.run_next()

    state = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()

    assert state["status"] == "failed"
    assert state["report"] is None
    assert state["execution"]["error"]["code"] == "provider_unavailable"
    assert "sk-live-1" not in json.dumps(state, ensure_ascii=False)
    assert state["capabilities"] == {"can_start": True, "can_cancel": False}


def test_an_invalid_provider_report_is_rejected_deterministically(tmp_path: Path) -> None:
    client, headers, dispatcher, revision_id = confirmed_task(tmp_path)
    invalid = report_document()
    invalid["facts"]["items"][0]["evidence_ids"] = []
    dispatcher.provider.outcomes.append(
        ZhiyanProviderResult(
            report_text=json.dumps(invalid, ensure_ascii=False),
            search_actions=(SearchAction(kind="open_page", url=OPENED_URL),),
            model="deepseek-v4-flash",
        )
    )
    client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)
    dispatcher.run_next()

    state = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()

    assert state["status"] == "failed"
    assert state["execution"]["error"]["code"] == "unsupported_fact_verdict"


def test_evidence_the_provider_never_opened_is_rejected(tmp_path: Path) -> None:
    client, headers, dispatcher, revision_id = confirmed_task(tmp_path)
    dispatcher.provider.outcomes.append(
        ZhiyanProviderResult(
            report_text=json.dumps(report_document(), ensure_ascii=False),
            search_actions=(SearchAction(kind="search", query="细颗粒物"),),
            model="deepseek-v4-flash",
        )
    )
    client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)
    dispatcher.run_next()

    state = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()

    assert state["execution"]["error"]["code"] == "unopened_evidence"


def test_a_retry_after_failure_can_still_produce_the_report(tmp_path: Path) -> None:
    client, headers, dispatcher, revision_id = confirmed_task(tmp_path)
    dispatcher.provider.outcomes.append(
        ZhiyanProviderFailure("provider_unavailable", "分析服务暂时不可用，请稍后重试。")
    )
    client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)
    dispatcher.run_next()

    retried = client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)
    dispatcher.run_next()

    assert retried.status_code == 202
    assert retried.json()["execution"]["attempt"] == 2
    state = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()
    assert state["status"] == "succeeded"


def test_a_cancelled_run_cannot_become_a_report(tmp_path: Path) -> None:
    client, headers, dispatcher, revision_id = confirmed_task(tmp_path)
    started = client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)
    execution_id = started.json()["execution"]["id"]
    cancelled = client.post(f"/executions/{execution_id}/cancel", headers=headers)
    dispatcher.run_next()

    assert cancelled.status_code == 202
    state = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()
    assert state["status"] == "cancelled"
    assert state["report"] is None
    assert state["capabilities"] == {"can_start": True, "can_cancel": False}
    assert client.get(f"/executions/{execution_id}", headers=headers).json()["status"] == (
        "cancelled"
    )


def test_a_late_result_cannot_replace_an_accepted_report(tmp_path: Path) -> None:
    client, headers, dispatcher, revision_id = confirmed_task(tmp_path)
    dispatcher.provider.outcomes.append(
        ZhiyanProviderFailure("provider_unavailable", "分析服务暂时不可用，请稍后重试。")
    )
    client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)
    first_execution = dispatcher.execution_ids[0]
    dispatcher.run_next()
    client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)
    dispatcher.run_next()
    accepted = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()

    dispatcher.execution_ids.append(first_execution)
    dispatcher.provider.outcomes.append(
        ZhiyanProviderResult(
            report_text=json.dumps(report_document("迟到的分析结论。"), ensure_ascii=False),
            search_actions=(SearchAction(kind="open_page", url=OPENED_URL),),
            model="deepseek-v4-flash",
        )
    )
    dispatcher.run_next()

    unchanged = client.get(f"/source-revisions/{revision_id}/zhiyan", headers=headers).json()
    assert unchanged["report"] == accepted["report"]


def test_another_user_cannot_read_or_start_a_run(tmp_path: Path) -> None:
    client, headers, dispatcher, revision_id = confirmed_task(tmp_path)
    client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)
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
    client, headers, dispatcher, revision_id = confirmed_task(tmp_path)
    client.post(f"/source-revisions/{revision_id}/zhiyan-runs", headers=headers)
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
