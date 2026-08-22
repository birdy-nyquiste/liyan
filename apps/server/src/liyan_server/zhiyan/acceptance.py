"""Deterministic acceptance of untrusted provider output as a 知言报告.

Provider output is never trusted. A report becomes a 知言报告 only after every
rule here holds: the fixed seven-section schema, stable sequential F/V/L/I/E
identifiers, references that resolve inside the report, the five defined factual
verdicts coupled to evidence, and evidence the provider actually opened and that
a factual item actually uses.
"""

import json
from collections.abc import Iterable, Sequence
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationError

from liyan_server.zhiyan.failures import ZhiyanRunFailure
from liyan_server.zhiyan.report import (
    EVIDENCE_BEARING_VERDICTS,
    ZhiyanReportDocument,
)


class ZhiyanRejected(ZhiyanRunFailure):
    """A provider result that cannot become a 知言报告."""


INVALID_REPORT_MESSAGE = "知言报告未通过结构校验，请重试。"
INVALID_EVIDENCE_MESSAGE = "知言报告的证据未通过校验，请重试。"


def accept_report_text(
    report_text: str,
    *,
    opened_urls: Sequence[str],
) -> ZhiyanReportDocument:
    """Validate provider text and return the accepted 知言报告 document."""
    document = _parse(report_text)
    _require_sequential_identifiers(document)
    _require_explicit_empty_states(document)
    _require_resolvable_references(document)
    _require_verdict_evidence_coupling(document)
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


def _require_sequential_identifiers(document: ZhiyanReportDocument) -> None:
    for prefix, items in _identified_sections(document):
        expected = [f"{prefix}{position}" for position in range(1, len(items) + 1)]
        if [item.id for item in items] != expected:
            raise ZhiyanRejected(
                "invalid_report_identifier",
                INVALID_REPORT_MESSAGE,
                internal_error=f"{prefix} identifiers are not sequential.",
            )


def _require_explicit_empty_states(document: ZhiyanReportDocument) -> None:
    sections: dict[str, ListSection] = {
        "facts": document.facts,
        "viewpoints": document.viewpoints,
        "logic": document.logic,
        "intent": document.intent,
        "evidence": document.evidence,
    }
    for name, section in sections.items():
        stated = bool((section.empty_statement or "").strip())
        if bool(section.items) == stated:
            raise ZhiyanRejected(
                "missing_empty_state",
                INVALID_REPORT_MESSAGE,
                internal_error=f"Section {name} does not state exactly one of items or emptiness.",
            )


def _require_resolvable_references(document: ZhiyanReportDocument) -> None:
    evidence_ids = {item.id for item in document.evidence.items}
    claim_ids = {item.id for item in document.facts.items} | {
        item.id for item in document.viewpoints.items
    }
    for fact in document.facts.items:
        _require_distinct_known_refs(fact.evidence_refs, evidence_ids, fact.id)
    reasonings: tuple[Reasoning, ...] = (*document.logic.items, *document.intent.items)
    for reasoning in reasonings:
        _require_distinct_known_refs(reasoning.refs, claim_ids, reasoning.id)


def _require_distinct_known_refs(refs: Sequence[str], known: set[str], owner: str) -> None:
    if len(set(refs)) != len(refs) or not set(refs) <= known:
        raise ZhiyanRejected(
            "invalid_report_reference",
            INVALID_REPORT_MESSAGE,
            internal_error=f"Item {owner} references unknown or repeated identifiers.",
        )


def _require_verdict_evidence_coupling(document: ZhiyanReportDocument) -> None:
    for fact in document.facts.items:
        cites_evidence = bool(fact.evidence_refs)
        if cites_evidence != (fact.verdict in EVIDENCE_BEARING_VERDICTS):
            raise ZhiyanRejected(
                "unsupported_fact_verdict",
                INVALID_EVIDENCE_MESSAGE,
                internal_error=f"Fact {fact.id} pairs verdict {fact.verdict} with "
                f"{len(fact.evidence_refs)} evidence references.",
            )


def _require_used_and_opened_evidence(
    document: ZhiyanReportDocument,
    opened_urls: Sequence[str],
) -> None:
    opened = {_comparable_url(url) for url in opened_urls}
    used = {ref for fact in document.facts.items for ref in fact.evidence_refs}
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


class Identified(Protocol):
    @property
    def id(self) -> str: ...


class ListSection(Protocol):
    @property
    def items(self) -> Sequence[Identified]: ...

    @property
    def empty_statement(self) -> str | None: ...


class Reasoning(Identified, Protocol):
    @property
    def refs(self) -> Sequence[str]: ...


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
