from collections.abc import Iterator
from datetime import UTC, datetime
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

from liyan_server.execution_states import (
    ExecutionStatus,
    PublishTaskStatus,
    RunOrigin,
    SourcePreparationStatus,
)


def aware_utc(moment: datetime) -> datetime:
    """SQLite returns naive timestamps; every stored moment is UTC."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


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
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )


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
    source_preparation_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("source_preparations.id", name="fk_source_revisions_source_preparation_id"),
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


class SourceEditSession(Base):
    """An intentionally unrecoverable browser editing checkpoint for 来源."""

    __tablename__ = "source_edit_sessions"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    base_version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("task_versions.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(16), default="active")
    save_idempotency_key: Mapped[str | None] = mapped_column(String(255))
    save_request_hash: Mapped[str | None] = mapped_column(String(64))
    saved_version_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("task_versions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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
        UniqueConstraint(
            "owner_id",
            "operation",
            "idempotency_key",
            name="uq_executions_owner_operation_idempotency",
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
    target_id: Mapped[UUID] = mapped_column(Uuid)
    input_version: Mapped[int] = mapped_column(Integer)
    input_identity: Mapped[str] = mapped_column(String(64))
    input_snapshot: Mapped[dict[str, object]] = mapped_column(JSON)
    attempt: Mapped[int] = mapped_column(Integer)
    origin: Mapped[RunOrigin] = mapped_column(String(16), default="initial")
    status: Mapped[ExecutionStatus] = mapped_column(String(32))
    trace_id: Mapped[UUID] = mapped_column(Uuid, default=uuid4)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    internal_error: Mapped[str | None] = mapped_column(Text)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_allowed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_id: Mapped[UUID | None] = mapped_column(
        Uuid,
    )
    #: Provider output that arrived too late to become business content, kept for
    #: tracing only (Technical Spec §6.4). Never returned to a client.
    stale_result: Mapped[dict[str, object] | None] = mapped_column(JSON)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    request_hash: Mapped[str | None] = mapped_column(String(64))


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


class ZhiyanReport(Base):
    """One immutable 知言报告 accepted for exactly one source Revision."""

    __tablename__ = "zhiyan_reports"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    execution_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("executions.id", ondelete="CASCADE"),
        unique=True,
    )
    owner_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    source_revision_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("source_revisions.id", ondelete="CASCADE"),
        unique=True,
    )
    prompt_version: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(64))
    provider_response_id: Mapped[str | None] = mapped_column(String(128))
    document: Mapped[dict[str, object]] = mapped_column(JSON)
    search_actions: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LiyanArticle(Base):
    """The stable generation target for one immutable 任务版本."""

    __tablename__ = "liyan_articles"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    task_version_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("task_versions.id", ondelete="CASCADE"),
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LiyanRunResult(Base):
    """One immutable complete article returned by a successful AgentRun."""

    __tablename__ = "liyan_run_results"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    execution_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("executions.id", ondelete="CASCADE"), unique=True
    )
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    article_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("liyan_articles.id", ondelete="CASCADE"), index=True
    )
    task_version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("task_versions.id", ondelete="CASCADE")
    )
    prompt_version: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(64))
    provider_response_id: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(255))
    body_markdown: Mapped[str] = mapped_column(Text)
    instruction: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LiyanRevision(Base):
    """One immutable article Revision created only by an explicit user Save."""

    __tablename__ = "liyan_revisions"
    __table_args__ = (
        UniqueConstraint("article_id", "number", name="uq_liyan_revisions_article_number"),
        UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_liyan_revisions_owner_idempotency_key",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    article_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("liyan_articles.id", ondelete="CASCADE"), index=True
    )
    task_version_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("task_versions.id", ondelete="CASCADE")
    )
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255))
    body_markdown: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    base_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("liyan_revisions.id", name="fk_liyan_revisions_base_revision_id")
    )
    restored_from_revision_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("liyan_revisions.id", name="fk_liyan_revisions_restored_from_revision_id"),
    )
    idempotency_key: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PublishTask(Base):
    """One independent attempt to place an immutable Revision on a 发布目标.

    Every column the platform needs is copied here at confirmation time, and the
    task, version, and Revision are recorded as plain identifiers rather than
    foreign keys: this record is evidence of a submission that already happened,
    so deleting the 立言任务 must not be able to take it with it.
    """

    __tablename__ = "publish_tasks"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_publish_tasks_owner_idempotency_key",
        ),
        #: One Revision reaches one 发布目标 at most once. Blog v0.11 has no
        #: idempotency key and no Preview lookup, so a duplicate could never be
        #: detected afterwards — the database is where it has to be impossible.
        UniqueConstraint(
            "revision_id",
            "target_key",
            name="uq_publish_tasks_revision_target",
        ),
        Index("ix_publish_tasks_owner_id", "owner_id"),
        Index("ix_publish_tasks_revision_id", "revision_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[UUID] = mapped_column(Uuid)
    task_display_name: Mapped[str] = mapped_column(String(255))
    task_version_id: Mapped[UUID] = mapped_column(Uuid)
    revision_id: Mapped[UUID] = mapped_column(Uuid)
    revision_number: Mapped[int] = mapped_column(Integer)
    target_key: Mapped[str] = mapped_column(String(64))
    target_platform: Mapped[str] = mapped_column(String(64))
    target_display_name: Mapped[str] = mapped_column(String(255))
    target_site_url: Mapped[str] = mapped_column(Text)
    target_api_base_url: Mapped[str] = mapped_column(Text)
    #: The name the user typed at confirmation, not a fact about the target.
    author: Mapped[str] = mapped_column(String(255))
    post_type: Mapped[str] = mapped_column(String(32))
    requested_status: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(255))
    body_markdown: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[PublishTaskStatus] = mapped_column(String(32))
    preview_url: Mapped[str | None] = mapped_column(Text)
    preview_path: Mapped[str | None] = mapped_column(Text)
    external_slug: Mapped[str | None] = mapped_column(String(255))
    external_version: Mapped[str | None] = mapped_column(String(64))
    response_evidence: Mapped[dict[str, object] | None] = mapped_column(JSON)
    failure_code: Mapped[str | None] = mapped_column(String(64))
    failure_message: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkerHeartbeat(Base):
    """The last time a worker process was known to be doing something.

    A worker that dies leaves no mark: queued work simply stays queued, and the
    API keeps answering, so nothing about the deployment looks wrong. One row
    per worker, rewritten as it runs, is what makes that silence observable.
    """

    __tablename__ = "worker_heartbeats"

    worker: Mapped[str] = mapped_column(String(255), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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
