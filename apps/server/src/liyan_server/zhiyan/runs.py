"""The durable identity of one 知言 run.

A queue message carries only an Execution identity, so the Execution's immutable
input snapshot is the single place that records what the run was approved to send:
which source Revision, its content hash, the Prompt and model versions, the tool
policy, and the run's current time.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Self
from uuid import UUID

from liyan_server.database import Execution, SourceRevision
from liyan_server.zhiyan.prompt import ZHIYAN_PROMPT_VERSION, AcceptedSourceRevision
from liyan_server.zhiyan.provider import ToolPolicy

ZHIYAN_OPERATION = "analyze_source"
ZHIYAN_TARGET_TYPE = "source_revision"


class InvalidRunSnapshot(Exception):
    """An Execution whose input snapshot cannot describe a 知言 run."""


@dataclass(frozen=True)
class ZhiyanRunSnapshot:
    source_revision_id: UUID
    content_hash: str
    prompt_version: str
    model: str
    requested_at: datetime
    tool_policy: ToolPolicy

    def as_json(self) -> dict[str, object]:
        return {
            "source_revision_id": str(self.source_revision_id),
            "content_hash": self.content_hash,
            "prompt_version": self.prompt_version,
            "model": self.model,
            "requested_at": self.requested_at.isoformat(),
            "web_search_enabled": self.tool_policy.web_search_enabled,
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> Self:
        try:
            return cls(
                source_revision_id=UUID(_text(payload, "source_revision_id")),
                content_hash=_text(payload, "content_hash"),
                prompt_version=_text(payload, "prompt_version"),
                model=_text(payload, "model"),
                requested_at=datetime.fromisoformat(_text(payload, "requested_at")),
                tool_policy=ToolPolicy(
                    web_search_enabled=bool(payload.get("web_search_enabled", True)),
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidRunSnapshot(str(error)) from error


def _text(payload: dict[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise TypeError(f"Snapshot field {key} is not text.")
    return value


def accepted_revision(revision: SourceRevision) -> AcceptedSourceRevision:
    return AcceptedSourceRevision(
        id=str(revision.id),
        title=revision.title,
        body=revision.body,
        provenance=revision.provenance,
        content_hash=revision.content_hash,
    )


def new_zhiyan_execution(
    revision: SourceRevision,
    *,
    owner_id: UUID,
    model: str,
    tool_policy: ToolPolicy,
    attempt: int,
    created_at: datetime,
    prompt_version: str = ZHIYAN_PROMPT_VERSION,
) -> Execution:
    snapshot = ZhiyanRunSnapshot(
        source_revision_id=revision.id,
        content_hash=revision.content_hash,
        prompt_version=prompt_version,
        model=model,
        requested_at=created_at,
        tool_policy=tool_policy,
    )
    identity = ":".join(
        ("zhiyan", str(revision.id), revision.content_hash, prompt_version, model)
    )
    return Execution(
        owner_id=owner_id,
        operation=ZHIYAN_OPERATION,
        target_type=ZHIYAN_TARGET_TYPE,
        target_id=revision.id,
        input_version=1,
        input_identity=hashlib.sha256(identity.encode()).hexdigest(),
        input_snapshot=snapshot.as_json(),
        attempt=attempt,
        status="queued",
        created_at=created_at,
    )
