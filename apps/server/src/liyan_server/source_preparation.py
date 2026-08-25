from dataclasses import dataclass

from fastapi import HTTPException, status

from liyan_server.source_text import without_nul


@dataclass(frozen=True)
class NormalizedSource:
    title: str
    body: str
    provenance: str | None


def normalize_source_content(
    *,
    title: str,
    body: str,
    provenance: str | None,
) -> NormalizedSource:
    normalized_title = " ".join(without_nul(title).split())
    normalized_body = (
        without_nul(body).replace("\r\n", "\n").replace("\r", "\n").strip()
    )
    normalized_provenance = " ".join(without_nul(provenance).split()) if provenance else ""
    errors: list[dict[str, str]] = []
    if not normalized_title:
        errors.append({"field": "title", "message": "A source title is required."})
    if not normalized_body:
        errors.append({"field": "body", "message": "A source body is required."})
    if errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=errors)
    return NormalizedSource(
        title=normalized_title,
        body=normalized_body,
        provenance=normalized_provenance or None,
    )


def source_warnings(
    *,
    body: str,
    provenance: str | None,
    short_source_characters: int,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if len(body) < short_source_characters:
        warnings.append(
            {
                "code": "short_body",
                "message": "The source body is short; confirm that it is complete.",
            }
        )
    if provenance is None:
        warnings.append(
            {
                "code": "missing_provenance",
                "message": "Provenance is missing; you can still create the task.",
            }
        )
    return warnings
