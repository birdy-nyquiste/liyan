"""Whether a worker is alive, and how anyone would know.

A dead Celery worker is the quietest failure this system has. Nothing raises,
the API keeps answering, readiness keeps saying the database is fine, and every
piece of work a user starts simply waits forever. The only way to tell an idle
worker from a gone one is to have it say so while it runs.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from liyan_server.database import Database, WorkerHeartbeat, aware_utc

logger = logging.getLogger(__name__)

type WorkerState = Literal["beating", "silent", "unknown"]

#: What beat is called in `worker_heartbeats`.
#:
#: Beat only schedules — it never executes a task — so the beat process can
#: never write its own row. What proves beat is alive is a scheduled task
#: arriving at all, because nothing else sends one. The worker that runs one
#: therefore writes this row on beat's behalf.
BEAT_WORKER = "liyan-beat"

#: How long a worker may say nothing before its silence is worth reporting.
#: Comfortably longer than the slowest run 立言阁 starts, so a worker part-way
#: through a 知言 analysis is never called dead.
DEFAULT_SILENCE = timedelta(minutes=15)


def record_heartbeat(database_url: str, worker: str, *, at: datetime | None = None) -> None:
    """Say that this worker was doing something just now.

    Written on the way into each run rather than on a timer of its own: a worker
    that is processing is by definition alive, and a worker with nothing to do
    is indistinguishable from a healthy idle one either way.
    """
    database = Database(database_url)
    if database.engine is None:
        return
    moment = at or datetime.now(UTC)
    try:
        with Session(database.engine) as session:
            existing = session.get(WorkerHeartbeat, worker)
            if existing is None:
                session.add(WorkerHeartbeat(worker=worker, last_seen_at=moment))
            else:
                existing.last_seen_at = moment
            session.commit()
    except Exception:
        # A heartbeat is diagnostic. Failing to record one must never be the
        # reason a user's 知言 run does not happen.
        logger.warning("worker_heartbeat_not_recorded", extra={"worker": worker})
    finally:
        database.dispose()


def worker_state(
    database: Database, *, silence: timedelta = DEFAULT_SILENCE, now: datetime | None = None
) -> WorkerState:
    """What readiness should say about the workers behind this deployment.

    `unknown` and `silent` are deliberately different. A deployment that has
    never run a worker looks the same in the database as one whose worker died
    before it ever started, but only the second is a regression — and an
    operator reading a fresh environment should not be shown an alarm.

    The verdict is the *worst* of the known workers, not the freshest. There are
    two processes here and they fail independently: beat can die while the
    worker keeps running, and taking the newest heartbeat would report a healthy
    deployment while nothing was ever cleaned up again.
    """
    if database.engine is None:
        return "unknown"
    moment = now or datetime.now(UTC)
    try:
        with Session(database.engine) as session:
            latest = list(session.scalars(select(WorkerHeartbeat)))
    except Exception:
        return "unknown"
    if not latest:
        return "unknown"
    stalest = min(aware_utc(beat.last_seen_at) for beat in latest)
    return "beating" if moment - stalest <= silence else "silent"


def silent_workers(
    database: Database, *, silence: timedelta = DEFAULT_SILENCE, now: datetime | None = None
) -> tuple[str, ...]:
    """Which workers have stopped reporting, so an alert can name one."""
    if database.engine is None:
        return ()
    moment = now or datetime.now(UTC)
    with Session(database.engine) as session:
        return tuple(
            sorted(
                beat.worker
                for beat in session.scalars(select(WorkerHeartbeat))
                if moment - aware_utc(beat.last_seen_at) > silence
            )
        )
