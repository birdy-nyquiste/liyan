"""Deterministic acceptance of untrusted provider output as a 主题知言报告.

The same discipline as `zhiyan/acceptance.py`, with one deliberate difference:
which sections owe evidence. There, only `facts` did, because every other
section judged the 来源 text that was in hand. Here nothing is in hand — the
whole report is a claim about what the internet holds — so `facts` and
`blind_spots` must each cite a page the run actually opened, while `viewpoints`
and `disagreements` may generalise over material without pinning one page,
because they describe a spread rather than assert a fact.
"""

import json
import re
from collections.abc import Iterable, Sequence
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationError

from liyan_server.theme.report import SECTION_PREFIXES, ThemeReportDocument
from liyan_server.zhiyan.failures import ZhiyanRunFailure

INVALID_REPORT_MESSAGE = "主题知言报告未通过结构校验，请重试。"
INVALID_EVIDENCE_MESSAGE = "主题知言报告的证据未通过校验，请重试。"

#: Identifiers need only be stable and unique inside one report, and to say
#: which section they came from — that is what makes a 胶囊 resolvable.
IDENTIFIER_PATTERN = re.compile(r"^(?P<prefix>T[FVDBE])-(?P<number>\d{2,})$")


class ThemeReportRejected(ZhiyanRunFailure):
    """A provider result that cannot become a 主题知言报告."""


class Identified(Protocol):
    @property
    def id(self) -> str: ...


class Citing(Identified, Protocol):
    @property
    def evidence_ids(self) -> list[str]: ...


class ListSection(Protocol):
    @property
    def items(self) -> Sequence[Identified]: ...

    @property
    def empty_state(self) -> str | None: ...


def accept_theme_report_text(
    report_text: str,
    *,
    opened_urls: Sequence[str],
) -> ThemeReportDocument:
    """Validate provider text and return the accepted 主题知言报告 document."""
    document = _parse(report_text)
    _require_well_formed_unique_identifiers(document)
    _require_explicit_empty_states(document)
    _require_resolvable_references(document)
    _require_evidence_where_it_is_owed(document)
    _require_used_and_opened_evidence(document, opened_urls)
    return document


def _parse(report_text: str) -> ThemeReportDocument:
    try:
        payload = json.loads(report_text)
    except ValueError as error:
        raise ThemeReportRejected(
            "invalid_report_schema", INVALID_REPORT_MESSAGE, internal_error=repr(error)
        ) from error
    try:
        return ThemeReportDocument.model_validate(payload)
    except ValidationError as error:
        raise ThemeReportRejected(
            "invalid_report_schema", INVALID_REPORT_MESSAGE, internal_error=str(error)
        ) from error


def _require_well_formed_unique_identifiers(document: ThemeReportDocument) -> None:
    for prefix, items in _identified_sections(document):
        seen: set[str] = set()
        for item in items:
            match = IDENTIFIER_PATTERN.match(item.id)
            if match is None or match.group("prefix") != prefix or item.id in seen:
                raise ThemeReportRejected(
                    "invalid_report_identifier",
                    INVALID_REPORT_MESSAGE,
                    internal_error=f"Identifier {item.id!r} is malformed or repeated.",
                )
            seen.add(item.id)


def _require_explicit_empty_states(document: ThemeReportDocument) -> None:
    for name, section in _list_sections(document).items():
        stated = bool((section.empty_state or "").strip())
        if bool(section.items) == stated:
            raise ThemeReportRejected(
                "missing_empty_state",
                INVALID_REPORT_MESSAGE,
                internal_error=f"Section {name} does not state exactly one of items or emptiness.",
            )


def _require_resolvable_references(document: ThemeReportDocument) -> None:
    evidence_ids = {item.id for item in document.evidence.items}
    for item in _citing_items(document):
        _require_distinct_known_refs(item.evidence_ids, evidence_ids, item.id)
    # The overview may only summarise judgements a later section carries.
    _require_distinct_known_refs(
        [finding.ref_id for finding in document.overview.key_findings],
        {item.id for item in _citing_items(document)},
        "overview",
    )


def _require_distinct_known_refs(
    refs: Sequence[str],
    known: set[str],
    owner: str,
) -> None:
    if len(set(refs)) != len(refs) or not set(refs) <= known:
        raise ThemeReportRejected(
            "invalid_report_reference",
            INVALID_REPORT_MESSAGE,
            internal_error=f"Item {owner} references unknown or repeated identifiers.",
        )


def _require_evidence_where_it_is_owed(document: ThemeReportDocument) -> None:
    """A fact or a blind spot with no page behind it is exactly what this refuses."""
    owed: tuple[Citing, ...] = (*document.facts.items, *document.blind_spots.items)
    for item in owed:
        if not item.evidence_ids:
            raise ThemeReportRejected(
                "unsupported_theme_claim",
                INVALID_EVIDENCE_MESSAGE,
                internal_error=f"Item {item.id} asserts something with no external evidence.",
            )


def _require_used_and_opened_evidence(
    document: ThemeReportDocument,
    opened_urls: Sequence[str],
) -> None:
    opened = {_comparable_url(url) for url in opened_urls}
    used = {ref for item in _citing_items(document) for ref in item.evidence_ids}
    for evidence in document.evidence.items:
        if urlsplit(evidence.url).scheme.casefold() not in {"http", "https"}:
            raise ThemeReportRejected(
                "unsupported_evidence_url",
                INVALID_EVIDENCE_MESSAGE,
                internal_error=f"Evidence {evidence.id} is not a web page.",
            )
        if _comparable_url(evidence.url) not in opened:
            raise ThemeReportRejected(
                "unopened_evidence",
                INVALID_EVIDENCE_MESSAGE,
                internal_error=f"Evidence {evidence.id} was never opened during the run.",
            )
        if evidence.id not in used:
            raise ThemeReportRejected(
                "unused_evidence",
                INVALID_EVIDENCE_MESSAGE,
                internal_error=f"Evidence {evidence.id} is not used by any item.",
            )


def _comparable_url(url: str) -> str:
    parts = urlsplit(url.strip())
    return urlunsplit(
        (
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            parts.path.rstrip("/") or "/",
            parts.query,
            "",
        )
    )


def _citing_items(document: ThemeReportDocument) -> tuple[Citing, ...]:
    """Every item that may name evidence, whether or not it must."""
    return (
        *document.facts.items,
        *document.viewpoints.items,
        *document.disagreements.items,
        *document.blind_spots.items,
    )


def _list_sections(document: ThemeReportDocument) -> dict[str, ListSection]:
    return {
        "facts": document.facts,
        "viewpoints": document.viewpoints,
        "disagreements": document.disagreements,
        "blind_spots": document.blind_spots,
        "evidence": document.evidence,
    }


def _identified_sections(
    document: ThemeReportDocument,
) -> Iterable[tuple[str, Sequence[Identified]]]:
    sections = _list_sections(document)
    return ((SECTION_PREFIXES[name], sections[name].items) for name in SECTION_PREFIXES)
