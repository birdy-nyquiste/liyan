from collections.abc import Iterator
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Engine,
    ForeignKey,
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
    __table_args__ = (
        UniqueConstraint("task_id", "number", name="uq_task_versions_task_number"),
    )

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
