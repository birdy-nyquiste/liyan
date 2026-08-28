"""预扣 that nothing else settles.

The eager path covers every terminal branch of both workers, and still misses
two: a run the stalled sweep gave up on, and a 预扣 taken for a run that was
never queued at all. Both leave a user's 额度 taken for work that will never
happen, with no error and no failed run to show for it — only a smaller number
than they expected.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from database_support import migrated_database
from sqlalchemy.orm import Session

from liyan_server import credits
from liyan_server.credit_reconciliation import ORPHANED_HOLD_GRACE, reconcile_settlements
from liyan_server.database import Database, Execution, User
from liyan_server.zhiyan.runs import ZHIYAN_TARGET_TYPE

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def a_writer(tmp_path: Path) -> tuple[str, Database, User]:
    database_url = migrated_database(tmp_path)
    database = Database(database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        user = User(auth_subject="subject-1", email="writer@example.com")
        session.add(user)
        session.flush()
        credits.grant(session, user.id, 1_000, now=NOW)
        session.commit()
        session.refresh(user)
    return database_url, database, user


def an_execution(database: Database, user: User, target: object, status: str) -> None:
    assert database.engine is not None
    with Session(database.engine) as session:
        session.add(
            Execution(
                owner_id=user.id,
                operation="analyze_source",
                target_type=ZHIYAN_TARGET_TYPE,
                target_id=target,
                input_version=1,
                input_identity="a" * 64,
                input_snapshot={},
                attempt=1,
                status=status,
                created_at=NOW,
            )
        )
        session.commit()


def balance(database: Database, user: User) -> int:
    assert database.engine is not None
    with Session(database.engine) as session:
        return credits.remaining(session, user.id)


def hold_for(database: Database, user: User, target: object, *, at: datetime = NOW) -> None:
    assert database.engine is not None
    with Session(database.engine) as session:
        credits.hold(
            session,
            user.id,
            target_type=ZHIYAN_TARGET_TYPE,
            target_id=target,  # type: ignore[arg-type]
            attempt=1,
            credits=56,
            now=at,
        )
        session.commit()


def test_a_run_the_sweep_gave_up_on_gives_its_额度_back(tmp_path: Path) -> None:
    """The stalled sweep ends a run without the worker ever reaching the code
    that settles, so nothing on the eager path can do this."""
    database_url, database, user = a_writer(tmp_path)
    target = uuid4()
    hold_for(database, user, target)
    an_execution(database, user, target, "stale")

    assert reconcile_settlements(database_url, now=NOW) == 1
    assert balance(database, user) == 1_000


def test_a_run_still_going_keeps_its_预扣(tmp_path: Path) -> None:
    database_url, database, user = a_writer(tmp_path)
    target = uuid4()
    hold_for(database, user, target)
    an_execution(database, user, target, "running")

    assert reconcile_settlements(database_url, now=NOW) == 0
    assert balance(database, user) == 944


def test_额度_held_for_work_that_was_never_queued_come_back(tmp_path: Path) -> None:
    """`queue_initial_runs` runs after the task transaction commits and swallows
    its own trouble on purpose, so a 任务版本 can exist holding 额度 for a run
    nothing ever dispatched. Without this, those 额度 are gone for good."""
    database_url, database, user = a_writer(tmp_path)
    hold_for(database, user, uuid4())

    assert reconcile_settlements(database_url, now=NOW + ORPHANED_HOLD_GRACE) == 1
    assert balance(database, user) == 1_000


def test_a_dispatch_still_in_flight_is_not_mistaken_for_one_that_failed(
    tmp_path: Path,
) -> None:
    database_url, database, user = a_writer(tmp_path)
    hold_for(database, user, uuid4())

    assert reconcile_settlements(database_url, now=NOW + timedelta(minutes=1)) == 0
    assert balance(database, user) == 944


def test_reconciling_twice_settles_once(tmp_path: Path) -> None:
    """The eager path and this one both running is the ordinary case."""
    database_url, database, user = a_writer(tmp_path)
    target = uuid4()
    hold_for(database, user, target)
    an_execution(database, user, target, "failed")

    assert reconcile_settlements(database_url, now=NOW) == 1
    assert reconcile_settlements(database_url, now=NOW) == 0
    assert balance(database, user) == 1_000
