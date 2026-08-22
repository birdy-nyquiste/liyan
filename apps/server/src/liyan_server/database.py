from collections.abc import Iterator
from uuid import UUID, uuid4

from sqlalchemy import Engine, ForeignKey, String, Uuid, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    auth_subject: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320))


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )


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
