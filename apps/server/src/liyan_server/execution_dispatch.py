"""Where queued work is sent, and which worker is shaped to receive it.

Two queues, split by what the work *costs a machine* rather than by what it
means. A URL 来源 launches Chromium at 150–250MB and needs a process to itself
on a 512MB instance. A 知言 run is an `httpx.post` sitting on a socket for two
to three minutes, using no meaningful memory and no CPU.

They were on one queue, so a memory budget was throttling a network wait: the
single slot that exists because of Chromium was being held for minutes at a time
by a run that never opens a page. Separating them lets each be sized for what it
actually is — one prefork child with a browser, several threads with sockets.

Both names live here and are imported by both sides. A producer that sends where
no consumer listens fails in the quietest way available: the API accepts the
work, the queue fills, the worker sits idle, and nothing anywhere reports a
problem.
"""

from typing import Protocol
from uuid import UUID

from celery import Celery  # type: ignore[import-untyped]

#: Chromium and the file parsers. Deliberately unrenamed: a new name strands
#: whatever is mid-flight on the old one across the deploy, for no benefit.
SOURCE_QUEUE = "source-processing"

#: Everything whose time is spent waiting on somebody else's server.
PROVIDER_QUEUE = "provider-runs"

#: Where an operation belongs. Absent means the heavy queue, because that is the
#: conservative answer: a new operation runs slowly beside Chromium until
#: somebody decides it is only a socket, which is a worse day than a crash but a
#: better one than an unbounded number of them sharing an interpreter.
QUEUE_BY_OPERATION: dict[str, str] = {
    "fetch_url": SOURCE_QUEUE,
    "parse_file": SOURCE_QUEUE,
    "analyze_source": PROVIDER_QUEUE,
    "analyze_theme": PROVIDER_QUEUE,
    "propose_themes": PROVIDER_QUEUE,
    "generate_article": PROVIDER_QUEUE,
    "publish_preview": PROVIDER_QUEUE,
}

#: Beat's own sweeps. Database and R2 work — the heavy queue's single slot is far
#: too scarce to spend on a sweep that could be waiting behind a 10MB PDF.
SCHEDULED_QUEUE = PROVIDER_QUEUE


def queue_for(operation: str) -> str:
    return QUEUE_BY_OPERATION.get(operation, SOURCE_QUEUE)


class ExecutionDispatcher(Protocol):
    def dispatch(self, execution_id: UUID, operation: str) -> None:
        """Send one Execution to the worker shaped for it.

        The operation is passed rather than looked up: every caller has just
        created the Execution row and holds it, and a dispatcher that had to
        read the database to decide a queue would turn one insert into two round
        trips on the hot path of every submission.
        """
        ...

    def is_reachable(self) -> bool:
        """Whether the broker answers right now.

        Readiness asks this because every 来源, 知言 run, 立言 generation, and Blog
        submission is queued work: a deployment that cannot reach the broker
        accepts requests it can never act on. Required rather than defaulted —
        an implementation that cannot say is one readiness must not vouch for.
        """
        ...


class CeleryExecutionDispatcher:
    def __init__(self, broker_url: str) -> None:
        self._celery = Celery("liyan-api-producer", broker=broker_url)

    def dispatch(self, execution_id: UUID, operation: str) -> None:
        self._celery.send_task(
            "liyan.process_execution",
            args=[str(execution_id)],
            queue=queue_for(operation),
        )

    def is_reachable(self) -> bool:
        # Bounded, because readiness is polled continuously and a probe that
        # hangs is worse than one that answers "no".
        try:
            connection = self._celery.connection_for_write()
            connection.ensure_connection(max_retries=0, timeout=2)
            connection.release()
        except Exception:
            return False
        return True
