"""What a running Execution is allowed to say about itself, and at what price.

`progress_recorder` is the only thing in this system that writes to a row while
the run that owns it is still in flight. Two properties matter and both are
tested here: it must be cheap enough that a chatty provider cannot flood the
database, and it must never be able to end a run — a report that cost six
minutes and twenty searches must not be lost because a progress write failed.
"""

from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from zhiyan_support import confirm_sources, latest_stored_run, zhiyan_client

from liyan_server.database import Database, Execution
from liyan_server.run_progress import progress_recorder
from liyan_server.zhiyan.provider import RunProgress


def a_run(tmp_path: Path) -> tuple[str, UUID]:
    """One real queued 知言 Execution, to write progress onto."""
    client, headers, dispatcher = zhiyan_client(tmp_path)
    _, revision_ids = confirm_sources(client, headers, ["Progress"])
    return dispatcher.database_url, latest_stored_run(dispatcher.database_url, revision_ids[0]).id


def counts(database_url: str, execution_id: UUID) -> tuple[int | None, int | None]:
    database = Database(database_url)
    assert database.engine is not None
    try:
        with Session(database.engine) as session:
            execution = session.scalar(select(Execution).where(Execution.id == execution_id))
            assert execution is not None
            return execution.searched_count, execution.opened_count
    finally:
        database.dispose()


def test_a_run_that_has_said_nothing_has_no_progress(tmp_path: Path) -> None:
    """Null, not zero. 'Has not reported' and 'searched nothing' are different."""
    database_url, execution_id = a_run(tmp_path)

    assert counts(database_url, execution_id) == (None, None)


def test_the_first_report_reaches_the_row(tmp_path: Path) -> None:
    database_url, execution_id = a_run(tmp_path)
    database = Database(database_url)
    try:
        record = progress_recorder(database, execution_id)

        record(RunProgress(searched=2, opened=7))

        assert counts(database_url, execution_id) == (2, 7)
    finally:
        database.dispose()


def test_progress_is_throttled_rather_than_written_on_every_search(tmp_path: Path) -> None:
    """A run announces a search every few seconds; the workbench polls slower.

    Writing each one would be dozens of transactions to move a number nobody
    sees move. The first lands immediately — a writer waiting on a silent panel
    should not wait two more seconds for the first sign of life — and the rest
    wait their turn.
    """
    database_url, execution_id = a_run(tmp_path)
    database = Database(database_url)
    ticks = iter([100.0, 100.5, 101.0, 103.5])
    try:
        record = progress_recorder(database, execution_id, now=lambda: next(ticks))

        record(RunProgress(searched=1, opened=1))
        record(RunProgress(searched=2, opened=4))  # 0.5s later: too soon
        record(RunProgress(searched=3, opened=9))  # 1.0s later: still too soon
        assert counts(database_url, execution_id) == (1, 1)

        record(RunProgress(searched=4, opened=12))  # 3.5s later: written
        assert counts(database_url, execution_id) == (4, 12)
    finally:
        database.dispose()


def test_a_progress_write_that_fails_does_not_end_the_run(tmp_path: Path) -> None:
    """The whole point: this is diagnostic, and diagnostics never cost work."""
    database_url, execution_id = a_run(tmp_path)
    # A database that cannot be written to at all, which is the shape of every
    # reason this write fails: a dead connection, a lock, a full disk.
    unreachable = Database("sqlite:////nonexistent-directory/liyan.db")

    record = progress_recorder(unreachable, execution_id)
    record(RunProgress(searched=3, opened=8))  # must not raise

    assert counts(database_url, execution_id) == (None, None)


def test_progress_belongs_to_one_run_and_does_not_touch_another(tmp_path: Path) -> None:
    database_url, execution_id = a_run(tmp_path)
    database = Database(database_url)
    try:
        progress_recorder(database, uuid4())(RunProgress(searched=9, opened=9))

        assert counts(database_url, execution_id) == (None, None)
    finally:
        database.dispose()
