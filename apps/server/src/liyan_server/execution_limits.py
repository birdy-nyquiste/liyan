"""How much queued work one user may hold at once.

There is one worker slot (`render.yaml` sets `--concurrency=1`, because a fully
imported copy of this application is roughly 110MB and a URL fetch launches
Chromium beside it). Every 来源 fetch, parse, 知言 run, 立言 generation, and Blog
submission competes for that slot, and nothing else bounds how many a single
user may stack onto it: the per-Revision rule stops a second run on the *same*
target, not a fifth 立言任务 whose three sources each want analyzing.

Unbounded, the failure is not an outage but a queue: one user's afternoon of
submissions sits ahead of everyone else's first request, every one of them
saying 处理中 and none of them wrong. This makes the ceiling explicit and says so
before the work is accepted, which is the difference between a refusal a user
can act on and a wait they cannot see the end of.

It is called at each entry point that starts work rather than wired in as a
dependency, because the entry points do not agree on when to ask: an idempotent
replay must never be refused — the runs it is repeating are exactly what put its
user at the ceiling — and saving a 来源编辑会话 is outside the ceiling entirely,
because refusing it would discard editing work rather than delay work the user
is asking to start. A blanket dependency would have to be turned off in more
places than it applied.

The check is deliberately not per-Execution. A user confirms a 任务创建会话 with
three 来源 and three 知言 runs follow from that one act; refusing the fourth
halfway through would leave a 任务版本 with some sources analyzed and some not,
for a reason the user never chose. So the question asked is whether the user is
already at the ceiling, and a batch admitted under it is admitted whole. The
real bound is therefore the limit plus the largest legitimate batch, which is
what `docs/operations/limits.md` states.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from liyan_server.database import Execution
from liyan_server.execution_states import ACTIVE_EXECUTION_STATUSES
from liyan_server.settings import Settings

AT_CAPACITY_MESSAGE = "你已有较多工作正在进行，请等其中一项完成后再发起新的。"


def _active_execution_count(session: Session, owner_id: UUID) -> int:
    """How many of this user's Executions are queued, running, or being cancelled."""
    return (
        session.scalar(
            select(func.count())
            .select_from(Execution)
            .where(
                Execution.owner_id == owner_id,
                Execution.status.in_(tuple(ACTIVE_EXECUTION_STATUSES)),
            )
        )
        or 0
    )


def refuse_when_at_capacity(session: Session, settings: Settings, *, owner_id: UUID) -> None:
    """Refuse new work when this user is already holding the queue.

    A limit of zero is no limit, which is what Local wants: a developer running
    the whole stack on one machine is not competing with anybody, and a ceiling
    that fires there costs an afternoon of confusion for no protection.

    429 rather than 409, and without a `Retry-After`: the wait is not a fixed
    backoff the server owns (as 知言 retry timing is) but "until one of your own
    runs finishes", which only the work itself can answer.
    """
    limit = settings.max_active_executions_per_user
    if limit <= 0:
        return
    if _active_execution_count(session, owner_id) < limit:
        return
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=AT_CAPACITY_MESSAGE,
    )
