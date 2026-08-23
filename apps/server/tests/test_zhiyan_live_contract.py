"""A real DeepSeek Responses API result, replayed offline.

Captured from `deepseek-v4-flash` on 2026-08-22 with native `web_search` and a
strict `json_schema` format. Replaying it keeps the adapter and acceptance rules
honest about what the provider actually sends, including the ```json fence and
the `#ws_call_id` fragment on `open_page` URLs.
"""

import json
from pathlib import Path
from typing import Any

from liyan_server.zhiyan.acceptance import accept_report_text
from liyan_server.zhiyan.deepseek import provider_result

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
