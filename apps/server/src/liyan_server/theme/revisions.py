"""What a 主题 is, and which snapshot one belongs to.

主题 is a special 来源, so it is not a field a 任务版本 carries but a snapshot a
任务版本 points at. Two things decide a snapshot's identity: the text, and the
来源 it was confirmed beside — because a 主题知言 run reads those 来源, so a report
bound to the text alone would answer for material it never saw.

That makes reuse fall out of the schema. Two versions agreeing on both reach the
same row and therefore the same report; editing a 来源 reaches a new row that
owes a new run; restoring an old version reaches the row that already exists.
"""

import hashlib
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from liyan_server.database import SourceRevision, ThemeRevision

#: One line, at most this long. `docs/design/the-theme.md`: a 主题 is a subject,
#: not a brief — the brief is 立言指令.
MAX_THEME_CHARACTERS = 80

TOO_LONG_MESSAGE = f"主题不能超过 {MAX_THEME_CHARACTERS} 个字。"


def normalized_theme(theme: str | None) -> str:
    """One line of plain text, or the empty string meaning no 主题.

    Newlines collapse to spaces rather than being refused: a 主题 pasted out of a
    document arrives with them through no fault of the user, and what they meant
    is unambiguous.
    """
    if theme is None:
        return ""
    collapsed = " ".join(theme.replace("\r\n", "\n").replace("\r", "\n").split())
    if len(collapsed) > MAX_THEME_CHARACTERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=TOO_LONG_MESSAGE,
        )
    return collapsed


def theme_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def source_context_hash(source_content_hashes: Sequence[str]) -> str:
    """The digest of the 来源 a 主题 was confirmed beside, in their own order.

    Ordered, because a 任务版本's 来源 are ordered and a run reads them in that
    order. Reordering two 来源 therefore produces a different 主题 snapshot, which
    is the honest answer: the run saw a different input.
    """
    digest = hashlib.sha256()
    for content_hash in source_content_hashes:
        digest.update(content_hash.encode())
        digest.update(b"\n")
    return digest.hexdigest()


def context_hash_of(revisions: Sequence[SourceRevision]) -> str:
    return source_context_hash([revision.content_hash for revision in revisions])


def theme_revision_for(
    session: Session,
    *,
    task_id: UUID,
    content: str,
    source_revisions: Sequence[SourceRevision],
    now: datetime,
) -> ThemeRevision | None:
    """The snapshot for this 主题 beside these 来源, existing or new.

    None when the 主题 is empty: a version with no 主题 points at nothing, runs no
    主题知言, and is gated on its 来源 alone — which is every 任务版本 that existed
    before 主题 did.
    """
    if not content:
        return None
    context = context_hash_of(source_revisions)
    content_hash = theme_content_hash(content)
    existing = session.scalar(
        select(ThemeRevision).where(
            ThemeRevision.task_id == task_id,
            ThemeRevision.content_hash == content_hash,
            ThemeRevision.source_context_hash == context,
        )
    )
    if existing is not None:
        return existing
    revision = ThemeRevision(
        task_id=task_id,
        content=content,
        content_hash=content_hash,
        source_context_hash=context,
        created_at=now,
    )
    session.add(revision)
    session.flush()
    return revision
