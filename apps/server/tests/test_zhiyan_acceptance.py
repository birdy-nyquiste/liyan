"""Acceptance rules from Agent Spec 知言 v0.4 §4.10."""

import json
from typing import Any

import pytest

from liyan_server.zhiyan.acceptance import ZhiyanRejected, accept_report_text

OPENED = ("https://autonomy.work/four-day-week-pilot", "https://press.example/story")


def valid_document() -> dict[str, Any]:
    """The Agent Spec worked example, reduced to what acceptance inspects."""
    return {
        "overview": {
            "content_summary": "原文以英国四天工作制试验为依据，呼吁政府全面强制实施。",
            "fact_check_summary": "共核查 2 项重要事实：1 项部分准确，1 项有证据反驳。",
            "key_findings": [
                {"ref_id": "F-01", "text": "35% 不代表所有企业。"},
                {"ref_id": "L-01", "text": "试验结果被推广到所有行业。"},
            ],
            "reading_note": "原文引用了真实试验，但改变了部分指标的适用范围。",
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
                },
                {
                    "id": "F-02",
                    "quote": "61家参与企业后来全部永久保留了四天工作制。",
                    "claim": "61 家参与企业全部永久实行。",
                    "verdict": "有证据反驳",
                    "explanation": "报告称 56 家继续实行，其中 18 家确认永久实行。",
                    "evidence_ids": ["E-01"],
                },
            ],
            "empty_state": None,
        },
        "viewpoints": {
            "items": [
                {
                    "id": "V-01",
                    "quote": "数据已经证明四天工作制对所有行业都有效。",
                    "viewpoint": "四天工作制已被证明适用于所有行业。",
                    "owner": "文章作者",
                    "analysis": "这是对试验适用范围的判断，超出试验能够直接证明的范围。",
                }
            ],
            "empty_state": None,
        },
        "logic": {
            "argument_chain": "试验出现积极结果 → 对所有行业有效 → 政府应全面强制实施。",
            "items": [
                {
                    "id": "L-01",
                    "quote": "数据已经证明四天工作制对所有行业都有效。",
                    "judgment": "结论超出了试验能够支持的范围。",
                    "explanation": "特定参与企业的试验不能证明所有行业获得相同结果。",
                    "related_ids": ["F-01", "V-01"],
                }
            ],
            "empty_state": None,
        },
        "intent": {
            "explicit_purpose": "支持四天工作制并呼吁政府全面实施。",
            "items": [
                {
                    "id": "I-01",
                    "quote": "政府就应立即要求所有企业实施。",
                    "possible_intent": "可能希望营造应当立即行动的紧迫感。",
                    "explanation": "全文采用确定性表达；另一种可能是压缩了研究条件。",
                }
            ],
            "target_audience": "关心劳动政策的公众和决策者。",
            "expression_methods": ["使用具体数字增强权威感", "以确定性措辞缩小讨论空间"],
            "empty_state": None,
        },
        "evidence": {
            "items": [
                {
                    "id": "E-01",
                    "title": "Autonomy: The UK's Four-Day Week Pilot",
                    "url": "https://autonomy.work/four-day-week-pilot",
                    "explanation": "说明参与企业数量与营收、压力、倦怠指标的实际统计口径。",
                }
            ],
            "empty_state": None,
        },
    }


def accept(document: dict[str, Any], opened: tuple[str, ...] = OPENED) -> Any:
    return accept_report_text(json.dumps(document, ensure_ascii=False), opened_urls=opened)


def test_the_worked_example_is_accepted_with_all_seven_sections() -> None:
    report = accept(valid_document())

    assert [item.id for item in report.facts.items] == ["F-01", "F-02"]
    assert report.facts.items[0].verdict == "部分准确"
    assert report.facts.items[0].quote.startswith("所有企业")
    assert report.logic.argument_chain.startswith("试验出现积极结果")
    assert report.intent.target_audience == "关心劳动政策的公众和决策者。"
    assert [finding.ref_id for finding in report.overview.key_findings] == ["F-01", "L-01"]


def test_malformed_provider_text_is_rejected() -> None:
    with pytest.raises(ZhiyanRejected) as rejection:
        accept_report_text("not json at all", opened_urls=OPENED)

    assert rejection.value.code == "invalid_report_schema"


def test_a_missing_section_is_rejected() -> None:
    document = valid_document()
    del document["intent"]

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "invalid_report_schema"


def test_a_missing_quote_is_rejected() -> None:
    document = valid_document()
    del document["facts"]["items"][0]["quote"]

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "invalid_report_schema"


def test_a_missing_argument_chain_is_rejected() -> None:
    document = valid_document()
    del document["logic"]["argument_chain"]

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "invalid_report_schema"


@pytest.mark.parametrize(
    "verdict",
    ["有证据支持", "有证据反驳", "部分准确", "存在争议", "暂无法核实"],
)
def test_each_defined_verdict_is_accepted(verdict: str) -> None:
    document = valid_document()
    document["facts"]["items"][0]["verdict"] = verdict

    report = accept(document)

    assert report.facts.items[0].verdict == verdict


def test_an_undefined_verdict_is_rejected() -> None:
    document = valid_document()
    document["facts"]["items"][0]["verdict"] = "基本属实"

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "invalid_report_schema"


def test_a_malformed_identifier_is_rejected() -> None:
    document = valid_document()
    document["facts"]["items"][1]["id"] = "F2"
    document["logic"]["items"][0]["related_ids"] = ["F-01"]

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "invalid_report_identifier"


def test_a_repeated_identifier_is_rejected() -> None:
    document = valid_document()
    document["facts"]["items"][1]["id"] = "F-01"

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "invalid_report_identifier"


def test_non_contiguous_identifiers_are_accepted() -> None:
    """§4.9 asks only that identifiers stay stable and unique within one report."""
    document = valid_document()
    document["facts"]["items"][1]["id"] = "F-07"
    document["logic"]["items"][0]["related_ids"] = ["F-01", "V-01"]

    report = accept(document)

    assert [item.id for item in report.facts.items] == ["F-01", "F-07"]


def test_a_reference_to_an_undefined_item_is_rejected() -> None:
    document = valid_document()
    document["logic"]["items"][0]["related_ids"] = ["F-01", "V-09"]

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "invalid_report_reference"


def test_an_overview_finding_with_no_matching_judgement_is_rejected() -> None:
    """§4.10: the overview may not introduce a judgement no later section carries."""
    document = valid_document()
    document["overview"]["key_findings"].append({"ref_id": "F-09", "text": "凭空出现的判断。"})

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "invalid_report_reference"


def test_an_overview_may_reference_a_logic_or_intent_item() -> None:
    document = valid_document()
    document["overview"]["key_findings"] = [
        {"ref_id": "V-01", "text": "作者的适用范围判断。"},
        {"ref_id": "I-01", "text": "紧迫感的表达方式。"},
    ]

    report = accept(document)

    assert [finding.ref_id for finding in report.overview.key_findings] == ["V-01", "I-01"]


def test_a_logic_item_cannot_reference_itself() -> None:
    document = valid_document()
    document["logic"]["items"][0]["related_ids"] = ["L-01"]

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "invalid_report_reference"


def test_a_repeated_reference_is_rejected() -> None:
    document = valid_document()
    document["logic"]["items"][0]["related_ids"] = ["F-01", "F-01"]

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "invalid_report_reference"


def test_an_empty_section_without_an_explicit_empty_state_is_rejected() -> None:
    document = valid_document()
    document["viewpoints"] = {"items": [], "empty_state": "   "}
    document["logic"]["items"][0]["related_ids"] = ["F-01"]

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "missing_empty_state"


def test_an_empty_section_with_an_explicit_empty_state_is_accepted() -> None:
    """A legal empty state is a successful report, not a failure."""
    document = valid_document()
    document["viewpoints"] = {"items": [], "empty_state": "来源中没有可归属的观点表达。"}
    document["logic"]["items"][0]["related_ids"] = ["F-01"]

    report = accept(document)

    assert report.viewpoints.items == []
    assert report.viewpoints.empty_state == "来源中没有可归属的观点表达。"


def test_an_empty_logic_section_keeps_its_argument_chain() -> None:
    document = valid_document()
    document["logic"] = {
        "argument_chain": "试验出现积极结果 → 政府应全面强制实施。",
        "items": [],
        "empty_state": "没有发现影响结论的明显逻辑问题。",
    }
    document["overview"]["key_findings"] = [{"ref_id": "F-01", "text": "35% 不代表所有企业。"}]

    report = accept(document)

    assert report.logic.items == []
    assert report.logic.argument_chain


def test_a_populated_section_carrying_an_empty_state_is_rejected() -> None:
    document = valid_document()
    document["facts"]["empty_state"] = "没有事实性声明。"

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "missing_empty_state"


def test_a_deterministic_verdict_without_evidence_is_rejected() -> None:
    document = valid_document()
    document["facts"]["items"][0]["evidence_ids"] = []

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "unsupported_fact_verdict"


def test_an_unverifiable_verdict_needs_no_evidence() -> None:
    """§3.5: 暂无法核实 is what a run uses when no reliable material was found."""
    document = valid_document()
    document["facts"]["items"][1]["verdict"] = "暂无法核实"
    document["facts"]["items"][1]["evidence_ids"] = []

    report = accept(document)

    assert report.facts.items[1].verdict == "暂无法核实"
    assert report.facts.items[1].evidence_ids == []


def test_evidence_the_provider_never_opened_is_rejected() -> None:
    document = valid_document()
    document["evidence"]["items"][0]["url"] = "https://invented.example/page"

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "unopened_evidence"


def test_evidence_matches_an_opened_page_ignoring_its_fragment() -> None:
    document = valid_document()
    document["evidence"]["items"][0]["url"] = "https://autonomy.work/four-day-week-pilot#table-3"

    report = accept(document)

    assert report.evidence.items[0].url.endswith("#table-3")


def test_evidence_no_factual_item_uses_is_rejected() -> None:
    document = valid_document()
    document["evidence"]["items"].append(
        {
            "id": "E-02",
            "title": "背景报道",
            "url": "https://press.example/story",
            "explanation": "只提供背景。",
        }
    )

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "unused_evidence"


def test_a_non_web_evidence_url_is_rejected() -> None:
    document = valid_document()
    document["evidence"]["items"][0]["url"] = "javascript:alert(1)"

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document, opened=("javascript:alert(1)",))

    assert rejection.value.code == "unsupported_evidence_url"


def test_a_blank_required_narrative_is_rejected() -> None:
    document = valid_document()
    document["overview"]["content_summary"] = "   "

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "invalid_report_schema"
