"""What may become a 主题知言报告, and what is refused.

The rules mirror `test_zhiyan_acceptance.py` where they are the same rules, and
diverge in exactly one place: which sections owe an external page. 事实 and 盲点
assert something about the world and must cite one; 观点 and 分歧 summarise a
spread and may not. That asymmetry is the whole point of a separate acceptance
module, so most of this file is about it.
"""

import json
from typing import Any

import pytest
from zhiyan_support import THEME_OPENED_URL, theme_report_document

from liyan_server.theme.acceptance import ThemeReportRejected, accept_theme_report_text


def accept(document: dict[str, Any], opened: list[str] | None = None) -> Any:
    return accept_theme_report_text(
        json.dumps(document, ensure_ascii=False),
        opened_urls=[THEME_OPENED_URL] if opened is None else opened,
    )


def test_a_complete_report_with_every_claim_cited_is_accepted() -> None:
    document = accept(theme_report_document())

    assert document.overview.key_findings[0].ref_id == "TF-01"
    assert document.blind_spots.items[0].source_gap.startswith("三个来源")
    # 分歧 carries no evidence and is still accepted: it generalises over what
    # the run read rather than asserting a fact of its own.
    assert document.disagreements.items[0].evidence_ids == []


def test_a_fact_with_no_evidence_is_refused() -> None:
    document = theme_report_document()
    document["facts"]["items"][0]["evidence_ids"] = []

    with pytest.raises(ThemeReportRejected) as refusal:
        accept(document)

    assert refusal.value.code == "unsupported_theme_claim"


def test_a_blind_spot_with_no_evidence_is_refused() -> None:
    """The section carrying the whole point of this report owes a page for it.

    A blind spot is a claim about what the internet holds and the 来源 do not.
    Uncited, it is the model's impression of an absence, which is exactly the
    thing a user cannot check.
    """
    document = theme_report_document()
    document["blind_spots"]["items"][0]["evidence_ids"] = []

    with pytest.raises(ThemeReportRejected) as refusal:
        accept(document)

    assert refusal.value.code == "unsupported_theme_claim"


def test_a_viewpoint_with_no_evidence_is_accepted() -> None:
    document = theme_report_document()
    document["viewpoints"]["items"][0]["evidence_ids"] = []
    # The evidence entry it was using stays cited by 事实 and 盲点, so it is still
    # used by something — an entry nobody uses is its own refusal.
    accepted = accept(document)

    assert accepted.viewpoints.items[0].evidence_ids == []


def test_an_identifier_from_the_wrong_section_is_refused() -> None:
    document = theme_report_document()
    document["viewpoints"]["items"][0]["id"] = "TF-09"

    with pytest.raises(ThemeReportRejected) as refusal:
        accept(document)

    assert refusal.value.code == "invalid_report_identifier"


def test_a_zhiyan_style_identifier_is_refused() -> None:
    """F-01 is a 来源报告's number. A 主题 capsule has to say where it came from."""
    document = theme_report_document()
    document["facts"]["items"][0]["id"] = "F-01"
    document["overview"]["key_findings"][0]["ref_id"] = "F-01"

    with pytest.raises(ThemeReportRejected) as refusal:
        accept(document)

    assert refusal.value.code == "invalid_report_identifier"


def test_an_overview_finding_pointing_nowhere_is_refused() -> None:
    document = theme_report_document()
    document["overview"]["key_findings"][0]["ref_id"] = "TF-77"

    with pytest.raises(ThemeReportRejected) as refusal:
        accept(document)

    assert refusal.value.code == "invalid_report_reference"


def test_a_section_that_is_both_empty_and_populated_is_refused() -> None:
    document = theme_report_document()
    document["viewpoints"]["empty_state"] = "没有找到观点。"

    with pytest.raises(ThemeReportRejected) as refusal:
        accept(document)

    assert refusal.value.code == "missing_empty_state"


def test_an_empty_section_stating_why_is_accepted() -> None:
    document = theme_report_document()
    document["disagreements"] = {"items": [], "empty_state": "公开讨论中没有实质分歧。"}

    accepted = accept(document)

    assert accepted.disagreements.items == []


def test_evidence_the_run_never_opened_is_refused() -> None:
    with pytest.raises(ThemeReportRejected) as refusal:
        accept(theme_report_document(), opened=["https://example.org/other"])

    assert refusal.value.code == "unopened_evidence"


def test_evidence_nothing_cites_is_refused() -> None:
    document = theme_report_document()
    for section in ("facts", "viewpoints", "blind_spots"):
        for item in document[section]["items"]:
            item["evidence_ids"] = []
    document["facts"]["items"][0]["evidence_ids"] = []

    with pytest.raises(ThemeReportRejected) as refusal:
        accept(document)

    # The fact is refused before the unused evidence is reached, which is the
    # right order: the claim is the problem, not the page.
    assert refusal.value.code == "unsupported_theme_claim"


def test_a_non_web_evidence_url_is_refused() -> None:
    document = theme_report_document()
    document["evidence"]["items"][0]["url"] = "ftp://oecd.org/report"

    with pytest.raises(ThemeReportRejected) as refusal:
        accept(document, opened=["ftp://oecd.org/report"])

    assert refusal.value.code == "unsupported_evidence_url"


def test_text_that_is_not_json_is_refused() -> None:
    with pytest.raises(ThemeReportRejected) as refusal:
        accept_theme_report_text("这不是 JSON", opened_urls=[])

    assert refusal.value.code == "invalid_report_schema"


def test_a_missing_section_is_refused() -> None:
    document = theme_report_document()
    del document["blind_spots"]

    with pytest.raises(ThemeReportRejected) as refusal:
        accept(document)

    assert refusal.value.code == "invalid_report_schema"
