"""The one place a test gets a migrated database, on whichever backend is asked.

By default every test gets its own SQLite file, which is fast and needs nothing
installed. Set `LIYAN_TEST_DATABASE_URL` to a PostgreSQL server and the same
tests run against it instead — one fresh database each, cloned from a template
migrated once.

The two backends are not interchangeable in the way that matters. SQLite does
not enforce foreign keys unless asked, and this project never asks, so a delete
that violates a constraint passes there and fails in production. That difference
is invisible until something runs on PostgreSQL, which is the point of this.
"""

import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import sqlalchemy

#: A PostgreSQL URL to run against, e.g.
#: postgresql+psycopg://liyan:liyan@localhost:5432/liyan_test
#: Unset means SQLite, which is the default everywhere except the CI job that
#: exists to catch what SQLite cannot see.
TEST_DATABASE_URL = "LIYAN_TEST_DATABASE_URL"

_TEMPLATE_SUFFIX = "_template"
_template_ready = False

#: Databases this run created, so each can be dropped when its test is over.
#: PostgreSQL caps connections, and a pooled engine per test holds its own until
#: the database goes; without this the suite exhausts the server part way in.
_created: list[str] = []


def migrated_database(tmp_path: Path) -> str:
    """A database at head, isolated from every other test's."""
    configured = os.environ.get(TEST_DATABASE_URL, "").strip()
    if not configured:
        return _migrated_sqlite(tmp_path)
    return _migrated_postgres(configured)


def _alembic_upgrade(database_url: str) -> None:
    project_root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=project_root,
        env=os.environ | {"LIYAN_DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _migrated_sqlite(tmp_path: Path) -> str:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'liyan.db'}"
    _alembic_upgrade(database_url)
    return database_url


def _migrated_postgres(configured: str) -> str:
    """A fresh database cloned from a template that was migrated once.

    Running the migrations per test would dominate the suite. Cloning is close
    to instant and still gives each test a database nothing else can touch.
    """
    global _template_ready
    base = sqlalchemy.make_url(configured)
    template = f"{base.database}{_TEMPLATE_SUFFIX}"
    if not _template_ready:
        _recreate(base, template)
        _alembic_upgrade(_url(base, template))
        _template_ready = True
    fresh = f"liyan_test_{uuid4().hex}"
    _recreate(base, fresh, template=template)
    _created.append(fresh)
    return _url(base, fresh)


def _url(base: sqlalchemy.URL, database: str) -> str:
    """The URL as a string, password intact.

    `str(URL)` renders the password as `***`, which reads like a working URL and
    fails to authenticate. Every URL here is built for a local test server, so
    nothing it names is a credential worth hiding from a traceback.
    """
    return base.set(database=database).render_as_string(hide_password=False)


def _recreate(base: sqlalchemy.URL, name: str, *, template: str | None = None) -> None:
    # AUTOCOMMIT because PostgreSQL refuses CREATE DATABASE inside a transaction.
    engine = sqlalchemy.create_engine(
        base.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT"
    )
    try:
        with engine.connect() as connection:
            connection.execute(sqlalchemy.text(f'DROP DATABASE IF EXISTS "{name}"'))
            clause = f' TEMPLATE "{template}"' if template else ""
            connection.execute(sqlalchemy.text(f'CREATE DATABASE "{name}"{clause}'))
    finally:
        engine.dispose()


def release_databases() -> None:
    """Drop everything this test created. A no-op on SQLite, which uses tmp_path."""
    configured = os.environ.get(TEST_DATABASE_URL, "").strip()
    if not configured or not _created:
        return
    base = sqlalchemy.make_url(configured)
    engine = sqlalchemy.create_engine(
        base.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT"
    )
    try:
        with engine.connect() as connection:
            while _created:
                name = _created.pop()
                # A pooled engine in the test still holds connections, and
                # PostgreSQL will not drop a database anyone is attached to.
                connection.execute(
                    sqlalchemy.text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :name AND pid <> pg_backend_pid()"
                    ),
                    {"name": name},
                )
                connection.execute(sqlalchemy.text(f'DROP DATABASE IF EXISTS "{name}"'))
    finally:
        engine.dispose()


class QueueSaying:
    """A broker that answers without one being there.

    Readiness probes the queue, so a test that reached a real broker would pass
    or fail on whether the developer happens to have Redis running.
    """

    def __init__(self, reachable: bool = True) -> None:
        self._reachable = reachable
        self.execution_ids: list[UUID] = []

    def dispatch(self, execution_id: UUID) -> None:
        self.execution_ids.append(execution_id)

    def is_reachable(self) -> bool:
        return self._reachable
