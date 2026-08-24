"""Test-wide setup, which for this suite means giving databases back.

Every test builds its own migrated database. On SQLite that is a file in
`tmp_path` and pytest disposes of it; on PostgreSQL it is a real database on a
server with a connection cap, so it has to be dropped explicitly or the suite
runs the server out of clients part way through.
"""

from collections.abc import Iterator

import pytest
from database_support import release_databases


@pytest.fixture(autouse=True)
def _release_test_databases() -> Iterator[None]:
    yield
    release_databases()
