import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Self
from uuid import UUID

from liyan_server.database import Execution, LiyanArticle
from liyan_server.execution_states import RunOrigin
from liyan_server.liyan.instruction import InstructionDocument
from liyan_server.liyan.prompt import LIYAN_PROMPT_VERSION

LIYAN_OPERATION = "generate_article"
LIYAN_TARGET_TYPE = "liyan_article"


class InvalidRunSnapshot(Exception):
    pass


@dataclass(frozen=True)
class LiyanRunSnapshot:
    article_id: UUID
    task_version_id: UUID
    prompt_version: str
    model: str
    requested_at: datetime
    input_text: str
    instruction: InstructionDocument
    working_copy: dict[str, str] | None

    def as_json(self) -> dict[str, object]:
        return {
            "article_id": str(self.article_id),
            "task_version_id": str(self.task_version_id),
            "prompt_version": self.prompt_version,
            "model": self.model,
            "requested_at": self.requested_at.isoformat(),
            "input_text": self.input_text,
            "instruction": self.instruction.model_dump(mode="json"),
            "working_copy": self.working_copy,
            "web_search_enabled": False,
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> Self:
        try:
            if payload.get("web_search_enabled") is not False:
                raise ValueError("A 立言 run must not enable Web Search.")
            return cls(
                article_id=UUID(_text(payload, "article_id")),
                task_version_id=UUID(_text(payload, "task_version_id")),
                prompt_version=_text(payload, "prompt_version"),
                model=_text(payload, "model"),
                requested_at=datetime.fromisoformat(_text(payload, "requested_at")),
                input_text=_text(payload, "input_text"),
                instruction=_instruction(payload.get("instruction")),
                working_copy=_working_copy(payload.get("working_copy")),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise InvalidRunSnapshot(str(error)) from error


def _text(payload: dict[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise TypeError(f"Snapshot field {key} is not text.")
    return value


def _working_copy(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError("Snapshot Working Copy is not an object.")
    title = value.get("title")
    body = value.get("body_markdown")
    if not isinstance(title, str) or not isinstance(body, str):
        raise TypeError("Snapshot Working Copy fields are not text.")
    return {"title": title, "body_markdown": body}


def _instruction(value: object) -> InstructionDocument:
    if isinstance(value, str):
        return InstructionDocument.from_text(value)
    return InstructionDocument.model_validate(value)


def new_liyan_execution(
    article: LiyanArticle,
    *,
    owner_id: UUID,
    model: str,
    input_text: str,
    instruction: InstructionDocument,
    working_copy: dict[str, str] | None,
    input_version: int,
    attempt: int,
    origin: RunOrigin,
    created_at: datetime,
    idempotency_key: str | None,
    request_hash: str,
    prompt_version: str = LIYAN_PROMPT_VERSION,
) -> Execution:
    snapshot = LiyanRunSnapshot(
        article_id=article.id,
        task_version_id=article.task_version_id,
        prompt_version=prompt_version,
        model=model,
        requested_at=created_at,
        input_text=input_text,
        instruction=instruction,
        working_copy=working_copy,
    )
    identity = ":".join(
        ("liyan", str(article.id), str(input_version), request_hash, prompt_version, model)
    )
    return Execution(
        owner_id=owner_id,
        operation=LIYAN_OPERATION,
        target_type=LIYAN_TARGET_TYPE,
        target_id=article.id,
        input_version=input_version,
        input_identity=hashlib.sha256(identity.encode()).hexdigest(),
        input_snapshot=snapshot.as_json(),
        attempt=attempt,
        origin=origin,
        status="queued",
        created_at=created_at,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
