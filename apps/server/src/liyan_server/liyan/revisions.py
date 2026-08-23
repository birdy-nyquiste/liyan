"""Immutable 文章 Revision history for one 立言文章.

A Revision exists only because the user pressed Save or restored an earlier one.
Auto-save, generation, and recovery of a completed AgentRun all stay outside this
module by construction: nothing here is reachable from the run pipeline.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from liyan_server.database import LiyanArticle, LiyanRevision
from liyan_server.hashing import canonical_hash

HISTORICAL_REVISION_LIMIT = 3

STALE_BASE = "文章已有更新的 Revision，请先查看最新内容。"
UNSAVED_EDITS = "有未保存的修改，请先保存后再发布。"
NOTHING_SAVED = "保存文章后才能发布。"


def article_content_hash(title: str, body_markdown: str) -> str:
    """The identity a browser can recompute to prove its draft matches a Revision."""
    return canonical_hash({"body_markdown": body_markdown, "title": title})


@dataclass(frozen=True)
class RevisionHistory:
    """The current Revision plus the bounded window of readable earlier ones."""

    current: LiyanRevision | None
    historical: list[LiyanRevision]

    def publishable(self, working_copy_hash: str | None) -> tuple[UUID | None, str | None]:
        if self.current is None:
            return None, NOTHING_SAVED
        if working_copy_hash is not None and working_copy_hash != self.current.content_hash:
            return None, UNSAVED_EDITS
        return self.current.id, None


def load_history(session: Session, article_id: UUID | None) -> RevisionHistory:
    if article_id is None:
        return RevisionHistory(current=None, historical=[])
    saved = list(
        session.scalars(
            select(LiyanRevision)
            .where(LiyanRevision.article_id == article_id)
            .order_by(LiyanRevision.number.desc())
            .limit(HISTORICAL_REVISION_LIMIT + 1)
        ).all()
    )
    if not saved:
        return RevisionHistory(current=None, historical=[])
    return RevisionHistory(current=saved[0], historical=saved[1:])


def new_revision(
    article: LiyanArticle,
    *,
    owner_id: UUID,
    previous: LiyanRevision | None,
    title: str,
    body_markdown: str,
    restored_from: LiyanRevision | None,
    idempotency_key: str,
    created_at: datetime,
) -> LiyanRevision:
    return LiyanRevision(
        owner_id=owner_id,
        article_id=article.id,
        task_version_id=article.task_version_id,
        number=previous.number + 1 if previous is not None else 1,
        title=title,
        body_markdown=body_markdown,
        content_hash=article_content_hash(title, body_markdown),
        base_revision_id=previous.id if previous is not None else None,
        restored_from_revision_id=restored_from.id if restored_from is not None else None,
        idempotency_key=idempotency_key,
        created_at=created_at,
    )
