"""Deterministic doubles for 知言 runs, shared by the 知言 API and orchestration tests.

No test here reaches DeepSeek. A recording dispatcher stands in for Celery so a
test decides exactly when each queued run executes, which is what makes partial
progress across several sources observable.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from blog_support import DeterministicBlogSubmitter
from database_support import entitle, migrated_database
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from liyan_server.app import create_app
from liyan_server.auth import InvalidAccessToken, VerifiedIdentity
from liyan_server.database import Database, Execution
from liyan_server.liyan.provider import (
    LiyanProviderFailure,
    LiyanProviderResult,
    LiyanRequest,
)
from liyan_server.liyan.runs import LIYAN_OPERATION
from liyan_server.liyan.worker import process_liyan_run
from liyan_server.provider_usage import ProviderUsage
from liyan_server.publication.runs import PUBLISH_OPERATION
from liyan_server.publication.worker import process_publication_run
from liyan_server.settings import Settings
from liyan_server.zhiyan.provider import (
    SearchAction,
    ZhiyanProviderFailure,
    ZhiyanProviderResult,
    ZhiyanRequest,
)
from liyan_server.zhiyan.runs import ZHIYAN_OPERATION
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


def accepted_result(
    summary: str = DEFAULT_SUMMARY, usage: ProviderUsage | None = None
) -> ZhiyanProviderResult:
    """One valid report. `usage` is absent by default, as the provider's own
    captured response is: a report that arrives without one is still a report,
    and most of these tests are about the report."""
    return ZhiyanProviderResult(
        report_text=json.dumps(report_document(summary), ensure_ascii=False),
        search_actions=(
            SearchAction(kind="search", query="四天工作制"),
            SearchAction(kind="open_page", url=OPENED_URL),
        ),
        model="deepseek-v4-flash",
        response_id="resp_1",
        usage=usage,
    )


def unavailable() -> ZhiyanProviderFailure:
    return ZhiyanProviderFailure("provider_unavailable", "分析服务暂时不可用，请稍后重试。")


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
    """Answers each run from a queue of outcomes, defaulting to one valid report."""

    def __init__(self) -> None:
        self.outcomes: list[ZhiyanProviderResult | ZhiyanProviderFailure] = []
        self.requests: list[ZhiyanRequest] = []

    def analyze(self, request: ZhiyanRequest) -> ZhiyanProviderResult:
        self.requests.append(request)
        outcome = self.outcomes.pop(0) if self.outcomes else accepted_result()
        if isinstance(outcome, ZhiyanProviderFailure):
            raise outcome
        return outcome


class DeterministicLiyanProvider:
    def __init__(self) -> None:
        self.outcomes: list[LiyanProviderResult | LiyanProviderFailure] = []
        self.requests: list[LiyanRequest] = []

    def generate(self, request: LiyanRequest) -> LiyanProviderResult:
        self.requests.append(request)
        outcome = self.outcomes.pop(0) if self.outcomes else LiyanProviderResult(
            article_text=json.dumps(
                {
                    "title": "四天工作制真正考验的是什么",
                    "body_markdown": (
                        "工时只是生产方式的一部分。\n\n"
                        "## 现实条件\n\n改变流程比压缩时间更重要。"
                    ),
                },
                ensure_ascii=False,
            ),
            model="deepseek-v4-flash",
            response_id="liyan_resp_1",
        )
        if isinstance(outcome, LiyanProviderFailure):
            raise outcome
        return outcome


class RecordingDispatcher:
    """Holds queued Executions so a test chooses when each one runs."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.execution_ids: list[UUID] = []
        self.provider = DeterministicZhiyanProvider()
        self.liyan_provider = DeterministicLiyanProvider()
        self.blog = DeterministicBlogSubmitter()

    def dispatch(self, execution_id: UUID) -> None:
        self.execution_ids.append(execution_id)

    def is_reachable(self) -> bool:
        return True

    def run_next(self) -> None:
        execution_id = self.execution_ids.pop(0)
        database = Database(self.database_url)
        assert database.engine is not None
        with Session(database.engine) as session:
            execution = session.get(Execution, execution_id)
            operation = execution.operation if execution else None
        database.dispose()
        if operation == PUBLISH_OPERATION:
            process_publication_run(
                self.database_url, execution_id, self.blog, "ingest-secret"
            )
        elif operation == LIYAN_OPERATION:
            process_liyan_run(
                self.database_url,
                execution_id,
                self.liyan_provider,
                self,
            )
        else:
            process_zhiyan_run(self.database_url, execution_id, self.provider, self)

    def run_all(self) -> None:
        while self.execution_ids:
            self.run_next()


def zhiyan_client(tmp_path: Path) -> tuple[TestClient, dict[str, str], RecordingDispatcher]:
    database_url = migrated_database(tmp_path)
    entitle(database_url)
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
    return client, {"Authorization": "Bearer allowed-token"}, dispatcher


def source_body(marker: str) -> str:
    return f"英国2022年的四天工作制试验已经证明了显著效果（{marker}）。" * 40


def confirm_single_source(
    client: TestClient,
    headers: dict[str, str],
    *,
    idempotency_key: str = "key-1",
) -> str:
    """Confirm one pasted source and return its initial SourceRevision id."""
    confirmation = client.post(
        "/task-creation/confirm",
        headers=headers,
        json={
            "idempotency_key": idempotency_key,
            "source": {
                "title": "四天工作制已经没有争议",
                "body": source_body("A"),
                "provenance": "https://press.example/story",
            },
        },
    )
    assert confirmation.status_code == 200, confirmation.text
    return str(confirmation.json()["source_revision"]["id"])


def create_session_sources(
    client: TestClient,
    headers: dict[str, str],
    titles: list[str],
    *,
    client_session_id: str = "session-1",
) -> list[str]:
    """Add pasted sources to a creation session and return their ids in order."""
    source_ids: list[str] = []
    for index, title in enumerate(titles):
        created = client.post(
            "/task-creation/pasted-sources",
            headers=headers,
            json={
                "client_session_id": client_session_id,
                "client_source_id": f"source-{index}",
                "title": title,
                "body": source_body(title),
                "provenance": f"https://press.example/{index}",
            },
        )
        assert created.status_code == 201, created.text
        source_ids.append(str(created.json()["id"]))
    return source_ids


def confirm_session(
    client: TestClient,
    headers: dict[str, str],
    source_ids: list[str],
    *,
    idempotency_key: str = "key-1",
    client_session_id: str = "session-1",
) -> tuple[str, list[str]]:
    """Confirm a creation session; return the task id and its Revision ids."""
    confirmation = client.post(
        "/task-creation/confirm",
        headers=headers,
        json={
            "idempotency_key": idempotency_key,
            "client_session_id": client_session_id,
            "source_ids": source_ids,
        },
    )
    assert confirmation.status_code == 200, confirmation.text
    payload = confirmation.json()
    return (
        str(payload["task"]["id"]),
        [str(revision["id"]) for revision in payload["source_revisions"]],
    )


def confirm_sources(
    client: TestClient,
    headers: dict[str, str],
    titles: list[str],
    *,
    idempotency_key: str = "key-1",
    client_session_id: str = "session-1",
) -> tuple[str, list[str]]:
    return confirm_session(
        client,
        headers,
        create_session_sources(client, headers, titles, client_session_id=client_session_id),
        idempotency_key=idempotency_key,
        client_session_id=client_session_id,
    )


def stored_runs(database_url: str, source_revision_id: str) -> list[Execution]:
    """Every 知言 Execution row for one Revision, oldest first.

    Failure reasons are deliberately absent from API responses, so a test that
    checks the server still recorded one reads the row itself.
    """
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


def latest_stored_run(database_url: str, source_revision_id: str) -> Execution:
    runs = stored_runs(database_url, source_revision_id)
    assert runs, "The source Revision has no 知言 run."
    return runs[-1]


def abandon_run(database_url: str, execution_id: str) -> None:
    """Fail an in-flight run from outside it, as the timeout sweep will.

    A worker that has already claimed a run keeps going after this, which is the
    only way a second run can start while the first is still physically running.
    """
    database = Database(database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        execution = session.get(Execution, UUID(execution_id))
        assert execution is not None
        execution.status = "failed"
        execution.error_code = "provider_unavailable"
        execution.error_message = "分析服务暂时不可用，请稍后重试。"
        execution.finished_at = datetime.now(UTC)
        execution.retry_allowed_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    database.dispose()


def elapse_retry_backoff(database_url: str, source_revision_id: str) -> None:
    """Move every stored retry moment for this target into the past.

    The server decides retry timing from a real clock, so a test that needs the
    backoff to have elapsed says so here rather than sleeping.
    """
    database = Database(database_url)
    assert database.engine is not None
    past = datetime.now(UTC) - timedelta(seconds=1)
    with Session(database.engine) as session:
        for execution in session.scalars(
            select(Execution).where(
                Execution.target_id == UUID(source_revision_id),
                Execution.operation == ZHIYAN_OPERATION,
            )
        ).all():
            if execution.retry_allowed_at is not None:
                execution.retry_allowed_at = past
        session.commit()
    database.dispose()
