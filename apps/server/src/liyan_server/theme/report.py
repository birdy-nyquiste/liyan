"""The typed 主题知言报告 envelope: six sections rather than 知言's seven.

知言's seven were designed to scrutinise one given text — `source` describes a
来源's genre and provenance, and the five 事实结论 adjudicate claims a 来源 made.
A 主题 is a subject, not a text, and makes no claims. What a reader needs of it
instead is what the internet holds on that subject and what their own 来源 leave
out, so the sections are: the landscape, established facts, the spread of
positions, where the argument turns, the angles the 来源 miss, and the pages the
run opened.

`docs/design/the-theme.md` is where these six and their evidence obligations are
argued; this module is their executable form.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from liyan_server.structured_output import provider_json_schema

type Narrative = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

UNATTRIBUTED_HOLDER = "归属不明确"

#: Which sections owe an external page for every item they carry, and which may
#: generalise without one. `facts` and `blind_spots` assert something about the
#: world; `viewpoints` and `disagreements` summarise material the run read.
CITING_SECTIONS: frozenset[str] = frozenset({"facts", "blind_spots"})
GENERALISING_SECTIONS: frozenset[str] = frozenset({"viewpoints", "disagreements"})

#: What each section's identifiers are prefixed with, in report order.
SECTION_PREFIXES: dict[str, str] = {
    "facts": "TF",
    "viewpoints": "TV",
    "disagreements": "TD",
    "blind_spots": "TB",
    "evidence": "TE",
}

#: Which kind of judgement one cited item is, as 立言 is told when a 胶囊 resolves.
type ThemeItemKind = Literal["fact", "viewpoint", "disagreement", "blind_spot"]


class ThemeModel(BaseModel):
    # As in 知言: the provider does not reliably honour additionalProperties, so
    # unspecified keys are dropped rather than fatal, and every declared field
    # stays required.
    model_config = ConfigDict(extra="ignore")


class ThemeKeyFinding(ThemeModel):
    ref_id: Narrative
    text: Narrative


class ThemeOverviewSection(ThemeModel):
    landscape: Narrative
    consensus_and_dispute: Narrative
    key_findings: list[ThemeKeyFinding]
    reading_note: Narrative


class ThemeFactItem(ThemeModel):
    id: Narrative
    claim: Narrative
    relevance: Narrative
    evidence_ids: list[str]


class ThemeViewpointItem(ThemeModel):
    id: Narrative
    position: Narrative
    holders: Narrative
    grounds: Narrative
    evidence_ids: list[str]


class ThemeDisagreementItem(ThemeModel):
    id: Narrative
    axis: Narrative
    sides: Narrative
    crux: Narrative
    evidence_ids: list[str]


class ThemeBlindSpotItem(ThemeModel):
    id: Narrative
    angle: Narrative
    source_gap: Narrative
    why_it_matters: Narrative
    evidence_ids: list[str]


class ThemeEvidenceItem(ThemeModel):
    id: Narrative
    title: Narrative
    url: Narrative
    explanation: Narrative


class ThemeFactSection(ThemeModel):
    items: list[ThemeFactItem]
    empty_state: str | None


class ThemeViewpointSection(ThemeModel):
    items: list[ThemeViewpointItem]
    empty_state: str | None


class ThemeDisagreementSection(ThemeModel):
    items: list[ThemeDisagreementItem]
    empty_state: str | None


class ThemeBlindSpotSection(ThemeModel):
    items: list[ThemeBlindSpotItem]
    empty_state: str | None


class ThemeEvidenceSection(ThemeModel):
    items: list[ThemeEvidenceItem]
    empty_state: str | None


class ThemeReportDocument(ThemeModel):
    """The six fixed sections of one 主题知言报告."""

    overview: ThemeOverviewSection
    facts: ThemeFactSection
    viewpoints: ThemeViewpointSection
    disagreements: ThemeDisagreementSection
    blind_spots: ThemeBlindSpotSection
    evidence: ThemeEvidenceSection


def theme_report_json_schema() -> dict[str, object]:
    """The provider-facing JSON Schema for structured 主题知言报告 output."""
    return provider_json_schema(ThemeReportDocument)
