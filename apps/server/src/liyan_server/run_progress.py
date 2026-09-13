"""What a running Execution has done so far, written where a poll can read it.

A provider run is the one part of this system a user waits minutes for, and for
all of those minutes `status` said only `running`. That is the same word for a
run on its twentieth page and a run whose worker died, and telling them apart is
the first thing anybody wants — so a searching run now leaves two counts behind
as it goes.

Writing them is diagnostic, never load-bearing. Every failure here is swallowed
and logged, following `worker_health.record_heartbeat`: a run that has already
searched twenty times must not be lost because the row saying so could not be
written. That is also why each write is its own short transaction rather than
part of the run's — a session held open across a six-minute provider call is a
lock held for six minutes, and nothing here is worth that.
"""

import logging
import time
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from liyan_server.database import Database, Execution
from liyan_server.zhiyan.provider import ProgressObserver, RunProgress

logger = logging.getLogger(__name__)

#: How often progress may reach the database. A run announces a search every few
#: seconds and the workbench polls far slower than that, so writing every one of
#: them would be perhaps sixty transactions a run to move a number the user sees
#: change twice. Two seconds keeps the display honest at a fraction of the cost.
MIN_WRITE_INTERVAL_SECONDS = 2.0


def progress_recorder(
    database: Database,
    execution_id: UUID,
    *,
    interval_seconds: float = MIN_WRITE_INTERVAL_SECONDS,
    now: object = None,
) -> ProgressObserver:
    """An observer that leaves a run's counts on its Execution row.

    Throttled rather than exhaustive, and deliberately not flushed at the end: a
    finished run's counts are on its report, and the last few searches of a run
    that is about to answer are of no interest to anybody. What matters is that
    the number moves while the user is watching it.
    """
    clock = now if callable(now) else time.monotonic
    last_written = 0.0

    def record(progress: RunProgress) -> None:
        nonlocal last_written
        moment = float(clock())
        if last_written and moment - last_written < interval_seconds:
            return
        last_written = moment
        try:
            if database.engine is None:
                return
            with Session(database.engine) as session:
                session.execute(
                    update(Execution)
                    .where(Execution.id == execution_id)
                    .values(
                        searched_count=progress.searched,
                        opened_count=progress.opened,
                    )
                )
                session.commit()
        except Exception:  # noqa: BLE001
            # Never the reason a run ends. One line, no stack: a database that
            # cannot take this write is already saying so somewhere louder.
            logger.warning(
                "execution_progress_not_recorded",
                extra={"execution_id": str(execution_id)},
            )

    return record
