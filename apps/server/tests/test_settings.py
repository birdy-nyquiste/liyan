"""Configuration this server has to accept as the platform hands it over.

A managed PostgreSQL gives out a URL in the shape the platform prefers, not the
shape this codebase happens to use. Render's `fromDatabase` wiring and Heroku's
DATABASE_URL both do it, neither can be edited into the right form by hand
without breaking the automatic wiring, and the failure is a build-time
ModuleNotFoundError for a driver nobody asked for.
"""

import pytest

from liyan_server.settings import Settings


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        # Render hands out this one.
        (
            "postgresql://liyan:secret@dpg-abc.singapore-postgres.render.com/liyan",
            "postgresql+psycopg://liyan:secret@dpg-abc.singapore-postgres.render.com/liyan",
        ),
        # Heroku's older shape, still common in platform documentation.
        (
            "postgres://liyan:secret@host:5432/liyan",
            "postgresql+psycopg://liyan:secret@host:5432/liyan",
        ),
    ],
)
def test_a_platform_postgres_url_is_pointed_at_the_installed_driver(
    given: str, expected: str
) -> None:
    """Without a driver, SQLAlchemy reaches for psycopg2, which is not installed."""
    assert Settings(database_url=given).database_url == expected


def test_a_url_that_already_names_its_driver_is_left_alone() -> None:
    """Naming psycopg2 is a deliberate choice, even if it would then fail."""
    for url in (
        "postgresql+psycopg://liyan:secret@localhost:5433/liyan",
        "postgresql+psycopg2://liyan:secret@localhost:5433/liyan",
        "sqlite+pysqlite:///./liyan.db",
    ):
        assert Settings(database_url=url).database_url == url


def test_a_password_with_an_at_sign_survives_the_rewrite() -> None:
    given = "postgresql://liyan:p%40ss@host:5432/liyan"

    assert Settings(database_url=given).database_url == (
        "postgresql+psycopg://liyan:p%40ss@host:5432/liyan"
    )
