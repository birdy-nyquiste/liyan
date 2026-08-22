import json
from typing import Any

import pytest

from liyan_server.zhiyan.acceptance import ZhiyanRejected, accept_report_text

OPENED = ("https://gov.example/report", "https://press.example/story")


def valid_document() -> dict[str, Any]:
    return {
        "overview": "这篇来源混合了可核查的统计声明与作者的政策立场。",
        "source": {
            "title": "城市空气质量年度回顾",
            "origin": "示例日报，署名记者",
            "material_type": "新闻评论",
            "context": "发表于年度环境公报之后。",
        },
        "facts": {
            "items": [
                {
                    "id": "F1",
                    "claim": "该市细颗粒物年均浓度较上一年下降了百分之十二。",
                    "verdict": "supported",
                    "reasoning": "官方公报给出了相同的年度降幅。",
                    "evidence_refs": ["E1"],
                },
                {
                    "id": "F2",
                    "claim": "新规使工业排放减半。",
                    "verdict": "unverifiable",
                    "reasoning": "未找到可靠的公开数据支持该幅度。",
                    "evidence_refs": [],
                },
            ],
            "empty_statement": None,
        },
        "viewpoints": {
            "items": [
                {
                    "id": "V1",
                    "holder": "作者",
                    "statement": "治理成效主要归功于新规。",
                    "assessment": "这是因果归因的立场，而非已核实的事实。",
                }
            ],
            "empty_statement": None,
        },
        "logic": {
            "items": [
                {
                    "id": "L1",
                    "finding": "以时间先后推断因果。",
                    "assessment": "浓度下降与新规同期发生，不足以证明因果关系。",
                    "refs": ["F1", "V1"],
                }
            ],
            "empty_statement": None,
        },
        "intent": {
            "items": [
                {
                    "id": "I1",
                    "finding": "为现行政策争取延续支持。",
                    "reasoning": "全文强调成效并回避成本讨论。",
                    "refs": ["V1"],
                }
            ],
            "empty_statement": None,
        },
        "evidence": {
            "items": [
                {
                    "id": "E1",
                    "title": "年度环境公报",
                    "url": "https://gov.example/report",
                    "publisher": "示例市生态环境局",
                    "relevance": "给出细颗粒物年均浓度的官方年度降幅。",
                }
            ],
            "empty_statement": None,
        },
    }


def accept(document: dict[str, Any], opened: tuple[str, ...] = OPENED) -> Any:
    return accept_report_text(json.dumps(document, ensure_ascii=False), opened_urls=opened)


def test_a_complete_report_is_accepted_with_stable_identifiers() -> None:
    report = accept(valid_document())

    assert [item.id for item in report.facts.items] == ["F1", "F2"]
    assert report.evidence.items[0].id == "E1"
    assert report.logic.items[0].refs == ["F1", "V1"]


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


def test_an_undefined_verdict_is_rejected() -> None:
    document = valid_document()
    document["facts"]["items"][0]["verdict"] = "mostly_true"

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "invalid_report_schema"


def test_out_of_sequence_identifiers_are_rejected() -> None:
    document = valid_document()
    document["facts"]["items"][1]["id"] = "F7"

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "invalid_report_identifier"


def test_a_reference_to_an_undefined_item_is_rejected() -> None:
    document = valid_document()
    document["logic"]["items"][0]["refs"] = ["F1", "V9"]

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "invalid_report_reference"


def test_a_repeated_reference_is_rejected() -> None:
    document = valid_document()
    document["intent"]["items"][0]["refs"] = ["V1", "V1"]

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "invalid_report_reference"


def test_an_empty_section_without_an_explicit_empty_statement_is_rejected() -> None:
    document = valid_document()
    document["viewpoints"] = {"items": [], "empty_statement": "   "}

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "missing_empty_state"


def test_an_empty_section_with_an_explicit_empty_statement_is_accepted() -> None:
    document = valid_document()
    document["viewpoints"] = {"items": [], "empty_statement": "来源中没有可归属的观点表达。"}
    document["logic"]["items"][0]["refs"] = ["F1"]
    document["intent"]["items"][0]["refs"] = ["F2"]

    report = accept(document)

    assert report.viewpoints.items == []
    assert report.viewpoints.empty_statement == "来源中没有可归属的观点表达。"


def test_a_populated_section_carrying_an_empty_statement_is_rejected() -> None:
    document = valid_document()
    document["facts"]["empty_statement"] = "没有事实性声明。"

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "missing_empty_state"


def test_a_supported_fact_without_evidence_is_rejected() -> None:
    document = valid_document()
    document["facts"]["items"][0]["evidence_refs"] = []
    document["evidence"] = {"items": [], "empty_statement": "没有可用证据。"}

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "unsupported_fact_verdict"


def test_an_unverifiable_fact_citing_evidence_is_rejected() -> None:
    document = valid_document()
    document["facts"]["items"][1]["evidence_refs"] = ["E1"]

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "unsupported_fact_verdict"


def test_evidence_the_provider_never_opened_is_rejected() -> None:
    document = valid_document()
    document["evidence"]["items"][0]["url"] = "https://invented.example/page"

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "unopened_evidence"


def test_evidence_matches_an_opened_page_ignoring_its_fragment() -> None:
    document = valid_document()
    document["evidence"]["items"][0]["url"] = "https://gov.example/report#table-3"

    report = accept(document)

    assert report.evidence.items[0].url == "https://gov.example/report#table-3"


def test_evidence_no_factual_item_uses_is_rejected() -> None:
    document = valid_document()
    document["evidence"]["items"].append(
        {
            "id": "E2",
            "title": "报道",
            "url": "https://press.example/story",
            "publisher": "示例通讯社",
            "relevance": "背景报道。",
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
    document["overview"] = "   "

    with pytest.raises(ZhiyanRejected) as rejection:
        accept(document)

    assert rejection.value.code == "invalid_report_schema"
