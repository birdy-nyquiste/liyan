"""The durable identity of one 主题 run, in both of its operations.

A queue message carries only an Execution identity, so an Execution's immutable
input snapshot is the single place recording what a run was approved to send.
Two operations live here because both are 主题 work and both are metered:
`propose_themes` reads the 来源 of a 任务创建会话 and returns candidates;
`analyze_theme` reads one 主题 snapshot and returns a 主题知言报告.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Self
from uuid import UUID

from liyan_server.database import Execution, ThemeProposal, ThemeRevision
from liyan_server.execution_states import RunOrigin
from liyan_server.theme.prompt import THEME_PROMPT_VERSION
from liyan_server.theme.proposal import PROPOSAL_PROMPT_VERSION
from liyan_server.zhiyan.provider import ToolPolicy

THEME_OPERATION = "analyze_theme"
THEME_TARGET_TYPE = "theme_revision"

PROPOSAL_OPERATION = "propose_themes"
PROPOSAL_TARGET_TYPE = "theme_proposal"


class InvalidRunSnapshot(Exception):
    """An Execution whose input snapshot cannot describe a 主题 run."""


@dataclass(frozen=True)
class ThemeRunSnapshot:
    theme_revision_id: UUID
    content_hash: str
    source_context_hash: str
    prompt_version: str
    model: str
    requested_at: datetime
    tool_policy: ToolPolicy

    def as_json(self) -> dict[str, object]:
        return {
            "theme_revision_id": str(self.theme_revision_id),
            "content_hash": self.content_hash,
            "source_context_hash": self.source_context_hash,
            "prompt_version": self.prompt_version,
            "model": self.model,
            "requested_at": self.requested_at.isoformat(),
            "web_search_enabled": self.tool_policy.web_search_enabled,
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> Self:
        try:
            return cls(
                theme_revision_id=UUID(_text(payload, "theme_revision_id")),
                content_hash=_text(payload, "content_hash"),
                source_context_hash=_text(payload, "source_context_hash"),
                prompt_version=_text(payload, "prompt_version"),
                model=_text(payload, "model"),
                requested_at=datetime.fromisoformat(_text(payload, "requested_at")),
                tool_policy=ToolPolicy(
                    web_search_enabled=bool(payload.get("web_search_enabled", True)),
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidRunSnapshot(str(error)) from error


@dataclass(frozen=True)
class ProposalRunSnapshot:
    """What one press of 提炼主题 was approved to read.

    The 来源 travel in the snapshot rather than being re-read by id, because
    where a press comes from decides whether they *can* be re-read. A
    任务创建会话's 来源 are rows on the server; a 来源编辑会话's are the version's
    revisions plus whatever the writer has typed over them, and that last part
    lives in the browser until it is saved. A run that re-read the durable rows
    would answer about text the writer is no longer looking at.

    `session_sources` says which case this was, so the worker still applies the
    one rule that only makes sense for a creation session: refuse a press whose
    session has changed since it was made.
    """

    proposal_id: UUID
    client_session_id: str
    source_context_hash: str
    sources: tuple[tuple[str, str, str | None], ...]
    session_sources: bool
    prompt_version: str
    model: str
    requested_at: datetime

    def as_json(self) -> dict[str, object]:
        return {
            "proposal_id": str(self.proposal_id),
            "client_session_id": self.client_session_id,
            "source_context_hash": self.source_context_hash,
            "sources": [
                {"title": title, "body": body, "provenance": provenance}
                for title, body, provenance in self.sources
            ],
            "session_sources": self.session_sources,
            "prompt_version": self.prompt_version,
            "model": self.model,
            "requested_at": self.requested_at.isoformat(),
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> Self:
        try:
            raw = payload["sources"]
            if not isinstance(raw, list):
                raise TypeError("Snapshot field sources is not a list.")
            sources: list[tuple[str, str, str | None]] = []
            for entry in raw:
                if not isinstance(entry, dict):
                    raise TypeError("A snapshot source is not an object.")
                provenance = entry.get("provenance")
                sources.append(
                    (
                        _text(entry, "title"),
                        _text(entry, "body"),
                        provenance if isinstance(provenance, str) else None,
                    )
                )
            return cls(
                proposal_id=UUID(_text(payload, "proposal_id")),
                client_session_id=_text(payload, "client_session_id"),
                source_context_hash=_text(payload, "source_context_hash"),
                sources=tuple(sources),
                session_sources=bool(payload.get("session_sources", True)),
                prompt_version=_text(payload, "prompt_version"),
                model=_text(payload, "model"),
                requested_at=datetime.fromisoformat(_text(payload, "requested_at")),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidRunSnapshot(str(error)) from error


def _text(payload: dict[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise TypeError(f"Snapshot field {key} is not text.")
    return value


def new_theme_execution(
    revision: ThemeRevision,
    *,
    owner_id: UUID,
    model: str,
    tool_policy: ToolPolicy,
    attempt: int,
    origin: RunOrigin,
    created_at: datetime,
    prompt_version: str = THEME_PROMPT_VERSION,
) -> Execution:
    snapshot = ThemeRunSnapshot(
        theme_revision_id=revision.id,
        content_hash=revision.content_hash,
        source_context_hash=revision.source_context_hash,
        prompt_version=prompt_version,
        model=model,
        requested_at=created_at,
        tool_policy=tool_policy,
    )
    identity = ":".join(
        (
            "theme",
            str(revision.id),
            revision.content_hash,
            revision.source_context_hash,
            prompt_version,
            model,
        )
    )
    return Execution(
        owner_id=owner_id,
        operation=THEME_OPERATION,
        target_type=THEME_TARGET_TYPE,
        target_id=revision.id,
        input_version=1,
        input_identity=hashlib.sha256(identity.encode()).hexdigest(),
        input_snapshot=snapshot.as_json(),
        attempt=attempt,
        origin=origin,
        status="queued",
        created_at=created_at,
    )


def new_proposal_execution(
    proposal: ThemeProposal,
    *,
    sources: Sequence[tuple[str, str, str | None]],
    session_sources: bool,
    model: str,
    attempt: int,
    created_at: datetime,
    prompt_version: str = PROPOSAL_PROMPT_VERSION,
) -> Execution:
    snapshot = ProposalRunSnapshot(
        proposal_id=proposal.id,
        client_session_id=proposal.client_session_id,
        source_context_hash=proposal.source_context_hash,
        sources=tuple(sources),
        session_sources=session_sources,
        prompt_version=prompt_version,
        model=model,
        requested_at=created_at,
    )
    identity = ":".join(
        (
            "theme-proposal",
            str(proposal.id),
            proposal.source_context_hash,
            prompt_version,
            model,
        )
    )
    return Execution(
        owner_id=proposal.owner_id,
        operation=PROPOSAL_OPERATION,
        target_type=PROPOSAL_TARGET_TYPE,
        target_id=proposal.id,
        input_version=1,
        input_identity=hashlib.sha256(identity.encode()).hexdigest(),
        input_snapshot=snapshot.as_json(),
        attempt=attempt,
        # Every press is the user's own act. There is no automatic recovery
        # attempt for a proposal: pressing again is the retry, and it is the
        # user's to spend.
        origin="initial",
        status="queued",
        created_at=created_at,
    )
