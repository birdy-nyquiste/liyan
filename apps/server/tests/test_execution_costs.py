"""What a run is recorded as having cost, and when it is recorded at all.

`usage` lives for the length of a provider call and nowhere else — not on the
Execution, not in the 知言报告. So unlike everything else operational here, a
cost cannot be reconciled by a later sweep: if the run ends without writing it
down, that run's cost is gone. These tests are about the paths where it would
be easy to end without writing it down.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from zhiyan_support import (
    DeterministicZhiyanProvider,
    accepted_result,
    confirm_sources,
    unavailable,
    zhiyan_client,
)

from liyan_server.database import Database, ExecutionCost
from liyan_server.provider_usage import ProviderUsage
from liyan_server.rate_card import CAPTURE_CREDITS, RATE_CARD_VERSION
from liyan_server.zhiyan.provider import ZhiyanProviderResult, ZhiyanRequest
from liyan_server.zhiyan.worker import process_zhiyan_run

SOURCES = ["四天工作制已经没有争议"]


def source_state(client: TestClient, headers: dict[str, str], task_id: str) -> dict[str, Any]:
    overview = client.get(f"/tasks/{task_id}/zhiyan", headers=headers)
    assert overview.status_code == 200, overview.text
    return dict(overview.json()["sources"][0])


USAGE = ProviderUsage(
    input_tokens=18_200,
    cached_input_tokens=2_000,
    output_tokens=4_000,
    reasoning_tokens=0,
    total_tokens=22_200,
)


def costs(database_url: str) -> list[ExecutionCost]:
    database = Database(database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        return list(session.scalars(select(ExecutionCost)))


def run_one(tmp_path: Path, provider: object) -> tuple[str, object]:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, SOURCES)
    execution_id = source_state(client, headers, task_id)["execution"]["id"]
    process_zhiyan_run(
        dispatcher.database_url,
        UUID(execution_id),
        provider,  # type: ignore[arg-type]
        dispatcher,
    )
    return dispatcher.database_url, execution_id


def test_a_successful_run_is_costed_and_chargeable(tmp_path: Path) -> None:
    class Provider(DeterministicZhiyanProvider):
        def analyze(self, request: ZhiyanRequest) -> ZhiyanProviderResult:
            return accepted_result(usage=USAGE)

    database_url, execution_id = run_one(tmp_path, Provider())

    (cost,) = costs(database_url)
    assert str(cost.execution_id) == execution_id
    assert cost.operation == "analyze_source"
    assert cost.rate_card_version == RATE_CARD_VERSION
    assert cost.input_tokens == 18_200
    assert cost.cached_input_tokens == 2_000
    assert cost.output_tokens == 4_000
    # One `search` action in the canned result. The least predictable term in
    # what a 知言 run costs, and the reason it is counted separately at all.
    assert cost.search_calls == 1
    assert cost.cost_micros is not None and cost.cost_micros > 0
    assert cost.charge_credits is not None and cost.charge_credits > 0


def test_a_run_that_never_reached_the_provider_is_costed_as_unknown(tmp_path: Path) -> None:
    """A row all the same, so the run is accounted for rather than absent.

    Its cost is unknown rather than zero: a call that failed in transport may
    have been billed for what the model generated before it broke, or may not
    have been billed at all, and 立言阁 cannot tell which from here. A null says
    that; a zero would claim to know.
    """

    class Provider(DeterministicZhiyanProvider):
        def analyze(self, request: ZhiyanRequest) -> ZhiyanProviderResult:
            raise unavailable()

    database_url, _ = run_one(tmp_path, Provider())

    (cost,) = costs(database_url)
    assert cost.operation == "analyze_source"
    assert cost.input_tokens is None
    assert cost.cost_micros is None
    assert cost.charge_credits is None


def test_a_report_nobody_kept_was_invoiced_all_the_same(tmp_path: Path) -> None:
    """A run cancelled while the provider was answering. The tokens were spent.

    This is where the cost of failure becomes measurable: the call returned, so
    what it consumed is known exactly, and the user is charged none of it. The
    gap between the two is how much this product absorbs — a number `credits.md`
    asserts is bounded and has never been able to check.
    """
    client, headers, dispatcher = zhiyan_client(tmp_path)
    task_id, _ = confirm_sources(client, headers, SOURCES)
    execution_id = source_state(client, headers, task_id)["execution"]["id"]

    class CancellingProvider(DeterministicZhiyanProvider):
        def analyze(self, request: ZhiyanRequest) -> ZhiyanProviderResult:
            client.post(f"/executions/{execution_id}/cancel", headers=headers)
            return accepted_result(usage=USAGE)

    process_zhiyan_run(
        dispatcher.database_url,
        UUID(execution_id),
        CancellingProvider(),
        dispatcher,
    )

    assert source_state(client, headers, task_id)["status"] == "cancelled"
    (cost,) = costs(dispatcher.database_url)
    assert cost.input_tokens == 18_200
    assert cost.cost_micros is not None and cost.cost_micros > 0
    assert cost.charge_credits == 0


def test_a_provider_that_reported_no_usage_leaves_the_cost_unknown(tmp_path: Path) -> None:
    """Unknown, not zero. Worker time alone would understate a 知言 run by two
    orders of magnitude and look like a real number while doing it."""

    class Provider(DeterministicZhiyanProvider):
        def analyze(self, request: ZhiyanRequest) -> ZhiyanProviderResult:
            return accepted_result()

    database_url, _ = run_one(tmp_path, Provider())

    (cost,) = costs(database_url)
    assert cost.cost_micros is None
    assert cost.charge_credits is None
    assert cost.worker_milliseconds is not None


def test_a_url_capture_is_costed_from_the_worker_it_held(tmp_path: Path) -> None:
    """No tokens and no bytes: a URL 来源 never reaches R2, so a fetch costs only
    the worker that held Chromium for it.

    It is charged the flat fee rather than what it measured, which is the whole
    reason both numbers are recorded — the gap between them is how anyone finds
    out whether three 额度 is still the right floor.
    """
    from test_url_source_api import authenticated_client

    client, headers, dispatcher = authenticated_client(tmp_path)
    created = client.post(
        "/task-creation/url-sources",
        headers=headers,
        json={
            "client_session_id": "session-1",
            "client_source_id": "source-1",
            "url": "https://example.com/story",
        },
    )
    assert created.status_code == 201, created.text
    dispatcher.run_next()

    (cost,) = costs(dispatcher.database_url)
    assert cost.operation == "fetch_url"
    assert cost.input_tokens is None
    assert cost.stored_bytes is None
    assert cost.model is None
    # Worker time is the whole of it, so the cost is known rather than unknown.
    assert cost.cost_micros is not None
    assert cost.worker_milliseconds is not None
    assert cost.charge_credits == CAPTURE_CREDITS
