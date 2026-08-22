"""The typed 知言报告 envelope, per Agent Spec 知言 v0.4.

The seven sections, their field names, and the five 事实结论 verdicts are product
decisions recorded in the Notion Agent Spec. This module is their executable
form: the provider's JSON Schema and the workbench's typed renderer both derive
from it, so neither can drift from the other.
"""

from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, StringConstraints

type FactVerdict = Literal[
    "有证据支持",
    "有证据反驳",
    "部分准确",
    "存在争议",
    "暂无法核实",
]

FACT_VERDICTS: frozenset[str] = frozenset(get_args(FactVerdict.__value__))
UNVERIFIABLE_VERDICT = "暂无法核实"
#: The four verdicts that assert something about the world and so owe evidence.
DETERMINISTIC_VERDICTS: frozenset[str] = FACT_VERDICTS - {UNVERIFIABLE_VERDICT}

UNATTRIBUTED_OWNER = "归属不明确"

type Narrative = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KeyFinding(ReportModel):
    ref_id: Narrative
    text: Narrative


class OverviewSection(ReportModel):
    content_summary: Narrative
    fact_check_summary: Narrative
    key_findings: list[KeyFinding]
    reading_note: Narrative


class SourceSection(ReportModel):
    genre: Narrative
    provenance: Narrative
    completeness: Narrative
    note: Narrative


class FactItem(ReportModel):
    id: Narrative
    quote: Narrative
    claim: Narrative
    verdict: FactVerdict
    explanation: Narrative
    evidence_ids: list[str]


class ViewpointItem(ReportModel):
    id: Narrative
    quote: Narrative
    viewpoint: Narrative
    owner: Narrative
    analysis: Narrative


class LogicItem(ReportModel):
    id: Narrative
    quote: Narrative
    judgment: Narrative
    explanation: Narrative
    related_ids: list[str]


class IntentItem(ReportModel):
    id: Narrative
    quote: Narrative
    possible_intent: Narrative
    explanation: Narrative


class EvidenceItem(ReportModel):
    id: Narrative
    title: Narrative
    url: Narrative
    explanation: Narrative


class FactSection(ReportModel):
    items: list[FactItem]
    empty_state: str | None


class ViewpointSection(ReportModel):
    items: list[ViewpointItem]
    empty_state: str | None


class LogicSection(ReportModel):
    argument_chain: Narrative
    items: list[LogicItem]
    empty_state: str | None


class IntentSection(ReportModel):
    explicit_purpose: Narrative
    items: list[IntentItem]
    target_audience: Narrative
    expression_methods: list[str]
    empty_state: str | None


class EvidenceSection(ReportModel):
    items: list[EvidenceItem]
    empty_state: str | None


class ZhiyanReportDocument(ReportModel):
    """The seven fixed sections of one 知言报告."""

    overview: OverviewSection
    source: SourceSection
    facts: FactSection
    viewpoints: ViewpointSection
    logic: LogicSection
    intent: IntentSection
    evidence: EvidenceSection


GENERATION_ONLY_KEYWORDS = frozenset({"minLength", "maxLength", "pattern", "format"})


def report_json_schema() -> dict[str, object]:
    """The provider-facing JSON Schema for structured 知言报告 output.

    Strict structured output accepts only a subset of JSON Schema, so keywords
    that merely tighten strings are dropped here. Application acceptance, not the
    provider schema, is what actually enforces them.
    """
    return _without_generation_only_keywords(ZhiyanReportDocument.model_json_schema())


def _without_generation_only_keywords(schema: object) -> dict[str, object]:
    if not isinstance(schema, dict):
        raise TypeError("A JSON Schema fragment must be an object.")
    cleaned: dict[str, object] = {}
    for key, value in schema.items():
        if key in GENERATION_ONLY_KEYWORDS:
            continue
        if isinstance(value, dict):
            cleaned[key] = _without_generation_only_keywords(value)
        elif isinstance(value, list):
            cleaned[key] = [
                _without_generation_only_keywords(entry) if isinstance(entry, dict) else entry
                for entry in value
            ]
        else:
            cleaned[key] = value
    return cleaned
