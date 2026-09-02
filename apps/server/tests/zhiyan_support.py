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
from liyan_server.theme.prompt import THEME_FORMAT_NAME
from liyan_server.theme.proposal import PROPOSAL_FORMAT_NAME
from liyan_server.theme.proposal_worker import process_theme_proposal_run
from liyan_server.theme.runs import PROPOSAL_OPERATION, THEME_OPERATION
from liyan_server.theme.worker import process_theme_run
from liyan_server.url_fetch_worker import UrlExtraction, UrlFetcher, process_url_fetch
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


THEME_OPENED_URL = "https://oecd.org/four-day-week-evidence"

DEFAULT_THEME = "四天工作制在不同行业的实际效果与代价"


def theme_report_document(
    landscape: str = "公共讨论集中在生产率与人力成本两条线上。",
) -> dict[str, Any]:
    """One valid 主题知言报告: six sections, TF/TV/TD/TB/TE ids, everything cited."""
    return {
        "overview": {
            "landscape": landscape,
            "consensus_and_dispute": "试验存在积极信号是共识，能否推广是争议。",
            "key_findings": [{"ref_id": "TF-01", "text": "试验样本以白领企业为主。"}],
            "reading_note": "三个来源都把「试验成功」当作既定前提，先看盲点一节。",
        },
        "facts": {
            "items": [
                {
                    "id": "TF-01",
                    "claim": "参与英国试验的企业以知识工作为主，制造业占比很低。",
                    "relevance": "决定试验结论能覆盖哪些行业。",
                    "evidence_ids": ["TE-01"],
                }
            ],
            "empty_state": None,
        },
        "viewpoints": {
            "items": [
                {
                    "id": "TV-01",
                    "position": "缩短工时会提高单位时间产出。",
                    "holders": "部分劳动经济学者与试验组织方。",
                    "grounds": "以试验期内营收与留存指标为依据。",
                    "evidence_ids": ["TE-01"],
                }
            ],
            "empty_state": None,
        },
        "disagreements": {
            "items": [
                {
                    "id": "TD-01",
                    "axis": "试验结论能否外推到连续生产行业。",
                    "sides": "支持方以自愿参与企业的数据为据，反对方指出班次制约。",
                    "crux": "分歧取决于事实差异：样本行业构成不同。",
                    "evidence_ids": [],
                }
            ],
            "empty_state": None,
        },
        "blind_spots": {
            "items": [
                {
                    "id": "TB-01",
                    "angle": "班次制行业的排班成本。",
                    "source_gap": "三个来源均未提及连续生产行业的排班安排。",
                    "why_it_matters": "这是政策能否全面推行的主要约束。",
                    "evidence_ids": ["TE-01"],
                }
            ],
            "empty_state": None,
        },
        "evidence": {
            "items": [
                {
                    "id": "TE-01",
                    "title": "OECD: Working time and productivity",
                    "url": THEME_OPENED_URL,
                    "explanation": "给出参与企业的行业构成与指标口径。",
                }
            ],
            "empty_state": None,
        },
    }


def theme_candidates() -> dict[str, Any]:
    return {
        "candidates": [
            {
                "theme": DEFAULT_THEME,
                "why": "三个来源都在谈四天工作制的效果与代价。",
            },
            {
                "theme": "四天工作制试验数据被引用时的口径问题",
                "why": "两个来源都引用了同一组数据。",
            },
            {
                "theme": "工时政策如何在行业之间产生不同后果",
                "why": "材料共同指向行业差异这一更大议题。",
            },
        ]
    }


def accepted_theme_result(
    landscape: str = "公共讨论集中在生产率与人力成本两条线上。",
) -> ZhiyanProviderResult:
    return ZhiyanProviderResult(
        report_text=json.dumps(theme_report_document(landscape), ensure_ascii=False),
        search_actions=(
            SearchAction(kind="search", query="four day week evidence"),
            SearchAction(kind="open_page", url=THEME_OPENED_URL),
        ),
        model="deepseek-v4-flash",
        response_id="theme_resp_1",
    )


def accepted_candidates_result() -> ZhiyanProviderResult:
    return ZhiyanProviderResult(
        report_text=json.dumps(theme_candidates(), ensure_ascii=False),
        search_actions=(),
        model="deepseek-v4-flash",
        response_id="proposal_resp_1",
    )


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
    """Answers each run from a queue of outcomes, defaulting to one valid report.

    One provider serves all three run kinds, as the real adapter does. Which
    default a run gets is read off the request's own `format_name` rather than
    from a flag a test has to remember to set: a 主题知言 run asking for a 来源
    report's shape would be a test that proves nothing.

    Each kind has its own outcome queue, so a test can fail one kind without
    having to know how many runs of another kind happen to be queued first.
    """

    def __init__(self) -> None:
        self.outcomes: list[ZhiyanProviderResult | ZhiyanProviderFailure] = []
        self.theme_outcomes: list[ZhiyanProviderResult | ZhiyanProviderFailure] = []
        self.proposal_outcomes: list[ZhiyanProviderResult | ZhiyanProviderFailure] = []
        self.requests: list[ZhiyanRequest] = []

    def analyze(self, request: ZhiyanRequest) -> ZhiyanProviderResult:
        self.requests.append(request)
        if request.format_name == THEME_FORMAT_NAME:
            queue, default = self.theme_outcomes, accepted_theme_result()
        elif request.format_name == PROPOSAL_FORMAT_NAME:
            queue, default = self.proposal_outcomes, accepted_candidates_result()
        else:
            queue, default = self.outcomes, accepted_result()
        outcome = queue.pop(0) if queue else default
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


#: The operation a 来源 fetch runs under. Spelled here because `url_api` writes
#: it as a literal and does not export it.
FETCH_URL_OPERATION = "fetch_url"


class DeterministicUrlFetcher:
    """A URL 来源 without a browser, or a network, or a page that might change.

    The body is long enough not to trip the short-source warning, because a
    warning is its own journey and not the one most tests are walking.
    """

    def __init__(self, title: str = "抓取到的文章标题") -> None:
        self.title = title
        self.fetched: list[str] = []

    def fetch(self, url: str) -> UrlExtraction:
        self.fetched.append(url)
        return UrlExtraction(
            title=self.title,
            body="四天工作制试验的营收、留存与健康指标被反复引用。" * 40,
            metadata={"source_url": url},
        )


class RecordingDispatcher:
    """Holds queued Executions so a test chooses when each one runs."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.execution_ids: list[UUID] = []
        self.provider = DeterministicZhiyanProvider()
        self.liyan_provider = DeterministicLiyanProvider()
        self.blog = DeterministicBlogSubmitter()
        self.url_fetcher: UrlFetcher = DeterministicUrlFetcher()

    def dispatch(self, execution_id: UUID, operation: str) -> None:
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
        elif operation == FETCH_URL_OPERATION:
            process_url_fetch(
                self.database_url,
                execution_id,
                self.url_fetcher,
                short_source_characters=500,
            )
        elif operation == LIYAN_OPERATION:
            process_liyan_run(
                self.database_url,
                execution_id,
                self.liyan_provider,
                self,
            )
        elif operation == ZHIYAN_OPERATION:
            process_zhiyan_run(self.database_url, execution_id, self.provider, self)
        elif operation == THEME_OPERATION:
            process_theme_run(self.database_url, execution_id, self.provider, self)
        elif operation == PROPOSAL_OPERATION:
            process_theme_proposal_run(self.database_url, execution_id, self.provider)
        else:
            # Never a silent default. 知言 used to be the fallback, and a
            # `fetch_url` Execution handed to it failed as invalid_run_snapshot
            # — an error about the wrong thing entirely, with the 来源 left at
            # 处理中 forever because nothing that could settle it ever ran.
            raise AssertionError(f"No double runs the {operation!r} operation.")

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
    theme: str | None = None,
) -> tuple[str, list[str]]:
    """Confirm a creation session; return the task id and its Revision ids.

    `theme` defaults to nothing, because most of this suite is about 来源 and an
    empty 主题 is a legitimate confirmation — a task confirmed without one
    behaves exactly as every task did before 主题 existed.
    """
    confirmation = client.post(
        "/task-creation/confirm",
        headers=headers,
        json={
            "idempotency_key": idempotency_key,
            "client_session_id": client_session_id,
            "source_ids": source_ids,
            "theme": theme,
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
    theme: str | None = None,
) -> tuple[str, list[str]]:
    return confirm_session(
        client,
        headers,
        create_session_sources(client, headers, titles, client_session_id=client_session_id),
        idempotency_key=idempotency_key,
        client_session_id=client_session_id,
        theme=theme,
    )


def theme_revision_id(client: TestClient, headers: dict[str, str], task_id: str) -> str:
    """The 主题 snapshot of a task's current version, as the 知言 area reports it."""
    state = client.get(f"/tasks/{task_id}/zhiyan", headers=headers)
    assert state.status_code == 200, state.text
    theme = state.json()["theme"]
    assert theme is not None, "The task version has no 主题."
    return str(theme["theme_revision_id"])


def stored_runs(
    database_url: str,
    source_revision_id: str,
    operation: str = ZHIYAN_OPERATION,
) -> list[Execution]:
    """Every Execution row of one operation for one target, oldest first.

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
                    Execution.operation == operation,
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


def latest_theme_run(database_url: str, theme_revision_id: str) -> Execution:
    runs = stored_runs(database_url, theme_revision_id, operation=THEME_OPERATION)
    assert runs, "The 主题 snapshot has no 主题知言 run."
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


def elapse_retry_backoff(
    database_url: str,
    source_revision_id: str,
    operation: str = ZHIYAN_OPERATION,
) -> None:
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
                Execution.operation == operation,
            )
        ).all():
            if execution.retry_allowed_at is not None:
                execution.retry_allowed_at = past
        session.commit()
    database.dispose()
