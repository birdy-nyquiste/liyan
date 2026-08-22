import hashlib
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import InstrumentedAttribute

from liyan_server.database import SourcePreparation, User

MAX_SESSION_SOURCES = 3


def normalized_session_identity(client_session_id: str) -> str:
    identity = client_session_id.strip()
    if not identity:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A client session identity is required.",
        )
    return identity


def lock_owner(session: Session, owner_id: UUID) -> User:
    user = session.scalar(select(User).where(User.id == owner_id).with_for_update())
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required.",
        )
    return user


def session_source_count(session: Session, owner_id: UUID, client_session_id: str) -> int:
    return (
        session.scalar(
            select(func.count(SourcePreparation.id)).where(
                SourcePreparation.owner_id == owner_id,
                SourcePreparation.client_session_id == client_session_id,
                SourcePreparation.confirmed_task_id.is_(None),
            )
        )
        or 0
    )


def ensure_session_capacity(
    session: Session,
    *,
    owner_id: UUID,
    client_session_id: str,
) -> None:
    lock_owner(session, owner_id)
    if session_source_count(session, owner_id, client_session_id) >= MAX_SESSION_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A task creation session can contain at most {MAX_SESSION_SOURCES} sources.",
        )


def normalized_body_hash(body: str) -> str:
    normalized = body.replace("\r\n", "\n").replace("\r", "\n").strip()
    return hashlib.sha256(normalized.encode()).hexdigest()


def ensure_unique_identity(
    session: Session,
    *,
    owner_id: UUID,
    client_session_id: str,
    kind: str,
    identity_column: InstrumentedAttribute[str | None],
    identity: str,
    excluding_source_id: UUID | None = None,
) -> None:
    statement = select(SourcePreparation.id).where(
        SourcePreparation.owner_id == owner_id,
        SourcePreparation.client_session_id == client_session_id,
        SourcePreparation.kind == kind,
        SourcePreparation.confirmed_task_id.is_(None),
        identity_column == identity,
    )
    if excluding_source_id is not None:
        statement = statement.where(SourcePreparation.id != excluding_source_id)
    if session.scalar(statement) is not None:
        labels = {
            "pasted": "This pasted source is already in the session.",
            "url": "This URL source is already in the session.",
            "file": "This file is already in the session.",
        }
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=labels[kind],
        )
