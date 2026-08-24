from typing import Protocol
from uuid import UUID

from celery import Celery  # type: ignore[import-untyped]


class ExecutionDispatcher(Protocol):
    def dispatch(self, execution_id: UUID) -> None: ...

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

    def dispatch(self, execution_id: UUID) -> None:
        self._celery.send_task(
            "liyan.process_execution",
            args=[str(execution_id)],
            queue="source-processing",
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
