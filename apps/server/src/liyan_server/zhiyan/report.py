"""The typed 知言报告 envelope that both the provider schema and the UI depend on."""

from typing import Annotated, Literal, get_args

from pydantic import BaseModel, ConfigDict, StringConstraints

type FactVerdict = Literal[
    "supported",
    "partially_supported",
    "disputed",
    "contradicted",
    "unverifiable",
]

FACT_VERDICTS: frozenset[str] = frozenset(get_args(FactVerdict.__value__))
EVIDENCE_BEARING_VERDICTS: frozenset[str] = FACT_VERDICTS - {"unverifiable"}


type Narrative = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceItem(ReportModel):
    id: Narrative
    title: Narrative
    url: Narrative
    publisher: Narrative
    relevance: Narrative


class FactItem(ReportModel):
    id: Narrative
    claim: Narrative
    verdict: FactVerdict
    reasoning: Narrative
    evidence_refs: list[str]


class ViewpointItem(ReportModel):
    id: Narrative
    holder: Narrative
    statement: Narrative
    assessment: Narrative


class LogicItem(ReportModel):
    id: Narrative
    finding: Narrative
    assessment: Narrative
    refs: list[str]


class IntentItem(ReportModel):
    id: Narrative
    finding: Narrative
    reasoning: Narrative
    refs: list[str]


class SourceSection(ReportModel):
    title: Narrative
    origin: Narrative
    material_type: Narrative
    context: Narrative


class FactSection(ReportModel):
    items: list[FactItem]
    empty_statement: str | None


class ViewpointSection(ReportModel):
    items: list[ViewpointItem]
    empty_statement: str | None


class LogicSection(ReportModel):
    items: list[LogicItem]
    empty_statement: str | None


class IntentSection(ReportModel):
    items: list[IntentItem]
    empty_statement: str | None


class EvidenceSection(ReportModel):
    items: list[EvidenceItem]
    empty_statement: str | None


class ZhiyanReportDocument(ReportModel):
    """The seven fixed sections of one 知言报告."""

    overview: Narrative
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
