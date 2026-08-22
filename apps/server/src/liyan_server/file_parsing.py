import signal
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import PurePath
from types import FrameType
from typing import BinaryIO
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader


class FileParseFailure(Exception):
    def __init__(self, code: str, message: str, internal_error: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.internal_error = internal_error


@dataclass(frozen=True)
class ParsedFile:
    title: str
    body: str
    metadata: dict[str, object]


@dataclass(frozen=True)
class FileParseLimits:
    max_pages: int
    max_normalized_characters: int
    timeout_seconds: int
    max_docx_entries: int
    max_docx_uncompressed_bytes: int


@contextmanager
def _enforce_wall_clock_timeout(timeout_seconds: int) -> Iterator[None]:
    if timeout_seconds <= 0:
        raise FileParseFailure(
            "parse_timeout",
            "The document took too long to process. Replace it with a smaller document.",
        )

    def timeout_handler(_: int, __: FrameType | None) -> None:
        raise FileParseFailure(
            "parse_timeout",
            "The document took too long to process. Replace it with a smaller document.",
        )

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, timeout_handler)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


def _check_deadline(started_at: float, timeout_seconds: int) -> None:
    if time.monotonic() - started_at > timeout_seconds:
        raise FileParseFailure(
            "parse_timeout",
            "The document took too long to process. Replace it with a smaller document.",
        )


def _normalize_body(body: str, *, max_characters: int) -> str:
    normalized = body.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise FileParseFailure(
            "empty_document",
            "No usable text was found in the document. Replace this source.",
        )
    if len(normalized) > max_characters:
        raise FileParseFailure(
            "normalized_text_too_large",
            "The document contains too much text. Replace it with a shorter document.",
        )
    return normalized


def _parse_text(stream: BinaryIO) -> tuple[str, dict[str, object]]:
    try:
        return stream.read().decode("utf-8-sig"), {}
    except UnicodeDecodeError as error:
        raise FileParseFailure(
            "invalid_text_encoding",
            "The text document must use UTF-8 encoding.",
            repr(error),
        ) from error


def _parse_pdf(
    stream: BinaryIO, *, max_pages: int, started_at: float, timeout_seconds: int
) -> tuple[str, dict[str, object]]:
    try:
        reader = PdfReader(stream)
        if reader.is_encrypted:
            raise FileParseFailure(
                "encrypted_document",
                "Encrypted documents are not supported. Upload an unlocked copy.",
            )
        page_count = len(reader.pages)
        if page_count > max_pages:
            raise FileParseFailure(
                "page_limit_exceeded",
                f"The document exceeds the {max_pages}-page limit.",
            )
        pages: list[str] = []
        for page in reader.pages:
            _check_deadline(started_at, timeout_seconds)
            pages.append(page.extract_text() or "")
        body = "\n\n".join(pages)
        if not body.strip():
            raise FileParseFailure(
                "scanned_document",
                "No selectable text was found. Scanned documents and OCR are not supported.",
            )
        return body, {"page_count": page_count}
    except FileParseFailure:
        raise
    except Exception as error:
        raise FileParseFailure(
            "damaged_document",
            "The PDF could not be read. Upload a valid, unencrypted document.",
            repr(error),
        ) from error


def _check_docx_archive(stream: BinaryIO, *, max_entries: int, max_uncompressed_bytes: int) -> None:
    try:
        with ZipFile(stream) as archive:
            entries = archive.infolist()
            uncompressed_bytes = sum(item.file_size for item in entries)
            if len(entries) > max_entries or uncompressed_bytes > max_uncompressed_bytes:
                raise FileParseFailure(
                    "document_resource_limit",
                    "The document is too complex to process safely.",
                )
            if "word/document.xml" not in archive.namelist():
                raise FileParseFailure(
                    "damaged_document",
                    "The DOCX file could not be read. Upload a valid document.",
                )
    except FileParseFailure:
        raise
    except BadZipFile as error:
        raise FileParseFailure(
            "damaged_document",
            "The DOCX file could not be read. Upload a valid document.",
            repr(error),
        ) from error
    finally:
        stream.seek(0)


def _parse_docx(
    stream: BinaryIO,
    *,
    max_entries: int,
    max_uncompressed_bytes: int,
    started_at: float,
    timeout_seconds: int,
) -> tuple[str, dict[str, object]]:
    header = stream.read(8)
    stream.seek(0)
    if header.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        raise FileParseFailure(
            "encrypted_document",
            "Encrypted documents are not supported. Upload an unlocked copy.",
        )
    _check_docx_archive(
        stream,
        max_entries=max_entries,
        max_uncompressed_bytes=max_uncompressed_bytes,
    )
    try:
        document = Document(stream)
        blocks: list[str] = []
        for block in document.iter_inner_content():
            _check_deadline(started_at, timeout_seconds)
            if isinstance(block, Paragraph):
                blocks.append(block.text)
            elif isinstance(block, Table):
                blocks.extend("\t".join(cell.text for cell in row.cells) for row in block.rows)
        return "\n".join(blocks), {"paragraph_count": len(document.paragraphs)}
    except FileParseFailure:
        raise
    except Exception as error:
        raise FileParseFailure(
            "damaged_document",
            "The DOCX file could not be read. Upload a valid document.",
            repr(error),
        ) from error


def parse_file(
    stream: BinaryIO,
    *,
    filename: str,
    content_type: str,
    limits: FileParseLimits,
) -> ParsedFile:
    started_at = time.monotonic()
    with _enforce_wall_clock_timeout(limits.timeout_seconds):
        if content_type in {"text/plain", "text/markdown"}:
            body, metadata = _parse_text(stream)
        elif content_type == "application/pdf":
            body, metadata = _parse_pdf(
                stream,
                max_pages=limits.max_pages,
                started_at=started_at,
                timeout_seconds=limits.timeout_seconds,
            )
        elif (
            content_type
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ):
            body, metadata = _parse_docx(
                stream,
                max_entries=limits.max_docx_entries,
                max_uncompressed_bytes=limits.max_docx_uncompressed_bytes,
                started_at=started_at,
                timeout_seconds=limits.timeout_seconds,
            )
        else:
            raise FileParseFailure(
                "unsupported_file_type",
                "This file type is not supported. Upload PDF, DOCX, TXT, or Markdown.",
            )
        _check_deadline(started_at, limits.timeout_seconds)
        normalized = _normalize_body(
            body,
            max_characters=limits.max_normalized_characters,
        )
    title = " ".join(PurePath(filename).stem.split()) or "Untitled source"
    return ParsedFile(title=title, body=normalized, metadata=metadata)
