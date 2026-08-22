from collections.abc import Iterator
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Engine,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    create_engine,
    text,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from liyan_server.execution_states import ExecutionStatus, SourcePreparationStatus


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    auth_subject: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320))
    next_task_number: Mapped[int] = mapped_column(Integer, default=1)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("owner_id", "number", name="uq_tasks_owner_number"),
        UniqueConstraint(
            "owner_id",
            "creation_idempotency_key",
            name="uq_tasks_owner_creation_idempotency_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    number: Mapped[int | None] = mapped_column(Integer)
    display_name: Mapped[str | None] = mapped_column(String(255))
    current_version_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("task_versions.id", name="fk_tasks_current_version_id", use_alter=True),
    )
    creation_idempotency_key: Mapped[str | None] = mapped_column(String(255))
    creation_request_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskVersion(Base):
    __tablename__ = "task_versions"
    __table_args__ = (UniqueConstraint("task_id", "number", name="uq_task_versions_task_number"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
    )
    number: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
    )


class SourceRevision(Base):
    __tablename__ = "source_revisions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("sources.id", ondelete="CASCADE"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    provenance: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskVersionSource(Base):
    __tablename__ = "task_version_sources"

    task_version_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("task_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_revision_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("source_revisions.id"),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer)


class SourcePreparation(Base):
    __tablename__ = "source_preparations"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "client_session_id",
            "client_source_id",
            name="uq_source_preparations_owner_client_identity",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    client_session_id: Mapped[str] = mapped_column(String(255))
    client_source_id: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32))
    input_url: Mapped[str | None] = mapped_column(Text)
    normalized_url: Mapped[str | None] = mapped_column(Text)
    filename: Mapped[str | None] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(255))
    object_key: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    input_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[SourcePreparationStatus] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(255))
    body: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_message: Mapped[str | None] = mapped_column(Text)
    active_execution_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "executions.id",
            name="fk_source_preparations_active_execution_id",
            use_alter=True,
        ),
    )
    accepted_result_id: Mapped[UUID | None] = mapped_column(
        Uuid,
    )
    confirmed_task_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Execution(Base):
    __tablename__ = "executions"
    __table_args__ = (
        UniqueConstraint(
            "target_id",
            "input_version",
            "attempt",
            name="uq_executions_target_input_attempt",
        ),
        Index("ix_executions_owner_id", "owner_id"),
        Index("ix_executions_target_id", "target_id"),
        Index(
            "uq_executions_one_active_per_target",
            "target_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running', 'cancel_requested')"),
            sqlite_where=text("status IN ('queued', 'running', 'cancel_requested')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    operation: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("source_preparations.id", ondelete="CASCADE"),
    )
    input_version: Mapped[int] = mapped_column(Integer)
    input_identity: Mapped[str] = mapped_column(String(64))
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSON)
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[ExecutionStatus] = mapped_column(String(32))
    trace_id: Mapped[UUID] = mapped_column(Uuid, default=uuid4)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    internal_error: Mapped[str | None] = mapped_column(Text)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_id: Mapped[UUID | None] = mapped_column(
        Uuid,
    )


class UrlFetchResult(Base):
    __tablename__ = "url_fetch_results"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    execution_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("executions.id", ondelete="CASCADE"),
        unique=True,
    )
    input_identity: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    provenance: Mapped[str] = mapped_column(Text)
    page_metadata: Mapped[dict[str, object]] = mapped_column("metadata", JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FileParseResult(Base):
    __tablename__ = "file_parse_results"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    execution_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("executions.id", ondelete="CASCADE"),
        unique=True,
    )
    input_identity: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    provenance: Mapped[str] = mapped_column(Text)
    document_metadata: Mapped[dict[str, object]] = mapped_column("metadata", JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Database:
    def __init__(self, database_url: str) -> None:
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        try:
            self.engine: Engine | None = create_engine(
                database_url,
                pool_pre_ping=True,
                connect_args=connect_args,
            )
        except SQLAlchemyError:
            self.engine = None
        self._sessions = (
            sessionmaker(self.engine, expire_on_commit=False) if self.engine is not None else None
        )

    def session(self) -> Iterator[Session]:
        if self._sessions is None:
            raise RuntimeError("Database is not configured.")
        with self._sessions() as session:
            yield session

    def is_available(self) -> bool:
        if self.engine is None:
            return False
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError:
            return False

    def dispose(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
