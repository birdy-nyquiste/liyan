"""Test-wide setup: give databases back, and read nobody's configuration.

Every test builds its own migrated database. On SQLite that is a file in
`tmp_path` and pytest disposes of it; on PostgreSQL it is a real database on a
server with a connection cap, so it has to be dropped explicitly or the suite
runs the server out of clients part way through.

And a `Settings` built in a test is built from what the test passes, never from
the machine it runs on.
"""

import os
from collections.abc import Iterator

import pytest
from database_support import release_databases

from liyan_server.settings import Settings

#: What `Settings` reads besides its arguments: a file beside the checkout, and
#: every `LIYAN_`-prefixed variable in the environment.
_ENV_PREFIX = "LIYAN_"

#: Except this one, which is how a run is pointed at PostgreSQL. It configures
#: the suite rather than the application, and `database_support` reads it
#: directly rather than through `Settings`.
_SUITE_OWNED = {"LIYAN_TEST_DATABASE_URL"}


@pytest.fixture(autouse=True, scope="session")
def _settings_ignore_the_machine() -> Iterator[None]:
    """Keep a developer's own configuration out of every `Settings` a test builds.

    `Settings` declares `env_file=".env"`, and the repository root usually holds
    one. A test that wrote `Settings(database_url=...)` and said nothing about
    the rest silently inherited whatever was in it — which is how
    `test_an_empty_allowlist_admits_any_verified_identity` came to pass on CI,
    where there is no `.env`, and fail on the machine of anyone who had put a
    real `LIYAN_ALLOWED_EMAILS` in theirs. The test was right and the
    environment answered for it.

    Session-scoped and autouse, because the alternative is asking every future
    test to remember, and the failure when one forgets is this one: green here,
    red there, and nothing on screen saying why.
    """
    original_env_file = Settings.model_config.get("env_file")
    leaked = {
        name: value
        for name, value in os.environ.items()
        if name.startswith(_ENV_PREFIX) and name not in _SUITE_OWNED
    }
    Settings.model_config["env_file"] = None
    for name in leaked:
        del os.environ[name]
    try:
        yield
    finally:
        os.environ.update(leaked)
        Settings.model_config["env_file"] = original_env_file


@pytest.fixture(autouse=True)
def _release_test_databases() -> Iterator[None]:
    yield
    release_databases()
