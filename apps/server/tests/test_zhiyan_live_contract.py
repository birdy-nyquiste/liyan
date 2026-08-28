"""A real DeepSeek Responses API result, replayed offline.

Captured from `deepseek-v4-flash` on 2026-08-22 with native `web_search` and a
strict `json_schema` format. Replaying it keeps the adapter and acceptance rules
honest about what the provider actually sends, including the ```json fence and
the `#ws_call_id` fragment on `open_page` URLs.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from liyan_server.zhiyan.acceptance import accept_report_text
from liyan_server.zhiyan.deepseek import (
    DeepSeekZhiyanProvider,
    ProviderHttpResponse,
    continuation_body,
    provider_result,
    read_response,
    request_body,
)
from liyan_server.zhiyan.prompt import AcceptedSourceRevision, zhiyan_request

FIXTURE = Path(__file__).parent / "fixtures" / "deepseek_live_response.json"


def live_payload() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(FIXTURE.read_text())
    return payload


def test_a_real_provider_response_becomes_an_accepted_report() -> None:
    result = provider_result(live_payload(), fallback_model="deepseek-v4-flash")

    report = accept_report_text(result.report_text, opened_urls=result.opened_urls)

    assert report.facts.items, "the captured run checked several claims"
    assert all(item.quote for item in report.facts.items)
    assert report.logic.argument_chain
    assert report.intent.target_audience
    assert report.overview.key_findings


def test_the_real_response_exercises_native_web_search() -> None:
    result = provider_result(live_payload(), fallback_model="deepseek-v4-flash")

    kinds = {action.kind for action in result.search_actions}

    assert "search" in kinds
    assert "open_page" in kinds
    assert result.opened_urls


def test_every_cited_url_resolves_against_a_provider_call_fragment() -> None:
    """The model cites clean URLs while open_page reports them with a fragment."""
    result = provider_result(live_payload(), fallback_model="deepseek-v4-flash")
    report = accept_report_text(result.report_text, opened_urls=result.opened_urls)

    assert any("#ws_call_id=" in url for url in result.opened_urls)
    assert all("#ws_call_id=" not in item.url for item in report.evidence.items)


def test_only_the_defined_verdicts_appear_in_a_real_report() -> None:
    from liyan_server.zhiyan.report import FACT_VERDICTS

    result = provider_result(live_payload(), fallback_model="deepseek-v4-flash")
    report = accept_report_text(result.report_text, opened_urls=result.opened_urls)

    assert {item.verdict for item in report.facts.items} <= FACT_VERDICTS


def test_the_captured_response_predates_usage_and_is_handled_anyway() -> None:
    """This capture was trimmed to what the adapter read at the time, so it
    carries no `usage` — which makes it the one piece of real provider output
    available to prove that a report survives a missing meter."""
    result = provider_result(live_payload(), fallback_model="deepseek-v4-flash")

    assert result.usage is None
    assert accept_report_text(result.report_text, opened_urls=result.opened_urls)


# --- Against the real API ----------------------------------------------------


REQUIRES_PROVIDERS = pytest.mark.skipif(
    os.environ.get("LIYAN_LIVE_PROVIDERS") != "1",
    reason="Set LIYAN_LIVE_PROVIDERS=1 to spend real DeepSeek credit in this check.",
)

CLAIM_BEARING = AcceptedSourceRevision(
    id="22222222-2222-4222-8222-222222222222",
    title="四天工作制已经没有争议",
    body=(
        "所有企业实行四天工作制后，营收都会增长35%。"
        "英国2022年的试验已经证明了这一点，政府应当立即全面强制实施。"
    ),
    provenance=None,
    content_hash="b" * 64,
)


def _live_post(url: str, headers: dict[str, str], body: dict[str, Any]) -> ProviderHttpResponse:
    import httpx

    response = httpx.post(url, headers=headers, json=body, timeout=300)
    try:
        payload: object = response.json()
    except ValueError:
        payload = None
    return ProviderHttpResponse(response.status_code, payload, response.text[:2_000])


def _live_request() -> Any:
    return zhiyan_request(
        CLAIM_BEARING, model=os.environ.get("LIYAN_ZHIYAN_MODEL", "deepseek-v4-flash"),
        now=datetime.now(UTC),
    )


@REQUIRES_PROVIDERS
def test_the_provider_accepts_its_own_search_calls_back_as_input() -> None:
    """The whole continuation mechanism rests on this, and no document says it.

    DeepSeek lists `web_search_call` and `reasoning` among the input item types,
    but a run that hits the ten-round search cap is only rescuable if the API
    really takes those items back — carrying provider-owned ids and fields this
    adapter does not model — rather than rejecting the request. Everything else
    about the continuation is tested offline against doubles; this is the one
    fact only the live API can settle.
    """
    key = os.environ["LIYAN_DEEPSEEK_API_KEY"]
    base = os.environ.get("LIYAN_DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    request = _live_request()

    first = _live_post(f"{base}/responses", headers, request_body(request))
    assert first.status_code == 200, first.body_text
    call = read_response(first.payload, fallback_model=request.model)
    assert call.output_items, "nothing to continue from"

    resumed = _live_post(
        f"{base}/responses",
        headers,
        continuation_body(request, prior_items=call.output_items, final=True),
    )

    assert resumed.status_code == 200, (
        "DeepSeek refused its own output items as input — the continuation "
        f"cannot work as built: {resumed.body_text}"
    )
    continued = read_response(resumed.payload, fallback_model=request.model)
    assert continued.report_text, "a tool-less continuation must return a message"


@REQUIRES_PROVIDERS
def test_a_real_run_still_produces_an_acceptable_report() -> None:
    """The adapter now loops; this proves the ordinary one-call path is intact."""
    provider = DeepSeekZhiyanProvider(
        api_key=os.environ["LIYAN_DEEPSEEK_API_KEY"],
        base_url=os.environ.get("LIYAN_DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )

    result = provider.analyze(_live_request())

    assert result.usage is not None, "a live run must report what it consumed"
    assert accept_report_text(result.report_text, opened_urls=result.opened_urls)
