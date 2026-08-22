"""Deterministic acceptance of untrusted provider output as a 知言报告.

Agent Spec 知言 v0.4 §4.10 lists what makes a run fail. Each rule below is one
of those conditions, so a provider result becomes business content only when all
of them hold. A legal empty state is a success, not a failure.
"""

import json
import re
from collections.abc import Iterable, Sequence
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationError

from liyan_server.zhiyan.failures import ZhiyanRunFailure
from liyan_server.zhiyan.report import (
    DETERMINISTIC_VERDICTS,
    ZhiyanReportDocument,
)

INVALID_REPORT_MESSAGE = "知言报告未通过结构校验，请重试。"
INVALID_EVIDENCE_MESSAGE = "知言报告的证据未通过校验，请重试。"

#: Identifiers need only be stable and unique inside one report (§4.9).
IDENTIFIER_PATTERN = re.compile(r"^(?P<prefix>[FVLIE])-(?P<number>\d{2,})$")


class ZhiyanRejected(ZhiyanRunFailure):
    """A provider result that cannot become a 知言报告."""


class Identified(Protocol):
    @property
    def id(self) -> str: ...


class ListSection(Protocol):
    @property
    def items(self) -> Sequence[Identified]: ...

    @property
    def empty_state(self) -> str | None: ...


def accept_report_text(
    report_text: str,
    *,
    opened_urls: Sequence[str],
) -> ZhiyanReportDocument:
    """Validate provider text and return the accepted 知言报告 document."""
    document = _parse(report_text)
    _require_well_formed_unique_identifiers(document)
    _require_explicit_empty_states(document)
    _require_resolvable_references(document)
    _require_evidence_for_deterministic_verdicts(document)
    _require_used_and_opened_evidence(document, opened_urls)
    return document


def _parse(report_text: str) -> ZhiyanReportDocument:
    try:
        payload = json.loads(report_text)
    except ValueError as error:
        raise ZhiyanRejected(
            "invalid_report_schema", INVALID_REPORT_MESSAGE, internal_error=repr(error)
        ) from error
    try:
        return ZhiyanReportDocument.model_validate(payload)
    except ValidationError as error:
        raise ZhiyanRejected(
            "invalid_report_schema", INVALID_REPORT_MESSAGE, internal_error=str(error)
        ) from error


def _require_well_formed_unique_identifiers(document: ZhiyanReportDocument) -> None:
    for prefix, items in _identified_sections(document):
        seen: set[str] = set()
        for item in items:
            match = IDENTIFIER_PATTERN.match(item.id)
            if match is None or match.group("prefix") != prefix or item.id in seen:
                raise ZhiyanRejected(
                    "invalid_report_identifier",
                    INVALID_REPORT_MESSAGE,
                    internal_error=f"Identifier {item.id!r} is malformed or repeated.",
                )
            seen.add(item.id)


def _require_explicit_empty_states(document: ZhiyanReportDocument) -> None:
    sections: dict[str, ListSection] = {
        "facts": document.facts,
        "viewpoints": document.viewpoints,
        "logic": document.logic,
        "intent": document.intent,
        "evidence": document.evidence,
    }
    for name, section in sections.items():
        stated = bool((section.empty_state or "").strip())
        if bool(section.items) == stated:
            raise ZhiyanRejected(
                "missing_empty_state",
                INVALID_REPORT_MESSAGE,
                internal_error=f"Section {name} does not state exactly one of items or emptiness.",
            )


def _require_resolvable_references(document: ZhiyanReportDocument) -> None:
    evidence_ids = {item.id for item in document.evidence.items}
    judgements: tuple[Identified, ...] = (
        *document.facts.items,
        *document.viewpoints.items,
        *document.logic.items,
        *document.intent.items,
    )
    judgement_ids = {item.id for item in judgements}
    for fact in document.facts.items:
        _require_distinct_known_refs(fact.evidence_ids, evidence_ids, fact.id)
    for item in document.logic.items:
        _require_distinct_known_refs(item.related_ids, judgement_ids - {item.id}, item.id)
    # §4.10: the overview may not introduce a judgement no later section carries.
    _require_distinct_known_refs(
        [finding.ref_id for finding in document.overview.key_findings],
        judgement_ids,
        "overview",
    )


def _require_distinct_known_refs(
    refs: Sequence[str],
    known: set[str],
    owner: str,
) -> None:
    if len(set(refs)) != len(refs) or not set(refs) <= known:
        raise ZhiyanRejected(
            "invalid_report_reference",
            INVALID_REPORT_MESSAGE,
            internal_error=f"Item {owner} references unknown or repeated identifiers.",
        )


def _require_evidence_for_deterministic_verdicts(document: ZhiyanReportDocument) -> None:
    for fact in document.facts.items:
        if fact.verdict in DETERMINISTIC_VERDICTS and not fact.evidence_ids:
            raise ZhiyanRejected(
                "unsupported_fact_verdict",
                INVALID_EVIDENCE_MESSAGE,
                internal_error=f"Fact {fact.id} states {fact.verdict} without evidence.",
            )


def _require_used_and_opened_evidence(
    document: ZhiyanReportDocument,
    opened_urls: Sequence[str],
) -> None:
    opened = {_comparable_url(url) for url in opened_urls}
    used = {ref for fact in document.facts.items for ref in fact.evidence_ids}
    for evidence in document.evidence.items:
        if urlsplit(evidence.url).scheme.casefold() not in {"http", "https"}:
            raise ZhiyanRejected(
                "unsupported_evidence_url",
                INVALID_EVIDENCE_MESSAGE,
                internal_error=f"Evidence {evidence.id} is not a web page.",
            )
        if _comparable_url(evidence.url) not in opened:
            raise ZhiyanRejected(
                "unopened_evidence",
                INVALID_EVIDENCE_MESSAGE,
                internal_error=f"Evidence {evidence.id} was never opened during the run.",
            )
        if evidence.id not in used:
            raise ZhiyanRejected(
                "unused_evidence",
                INVALID_EVIDENCE_MESSAGE,
                internal_error=f"Evidence {evidence.id} is not used by any factual item.",
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


def _identified_sections(
    document: ZhiyanReportDocument,
) -> Iterable[tuple[str, Sequence[Identified]]]:
    return (
        ("F", document.facts.items),
        ("V", document.viewpoints.items),
        ("L", document.logic.items),
        ("I", document.intent.items),
        ("E", document.evidence.items),
    )
