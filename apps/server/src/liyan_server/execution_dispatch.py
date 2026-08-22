from typing import Protocol
from uuid import UUID

from celery import Celery  # type: ignore[import-untyped]


class ExecutionDispatcher(Protocol):
    def dispatch(self, execution_id: UUID) -> None: ...


class CeleryExecutionDispatcher:
    def __init__(self, broker_url: str) -> None:
        self._celery = Celery("liyan-api-producer", broker=broker_url)

    def dispatch(self, execution_id: UUID) -> None:
        self._celery.send_task(
            "liyan.process_execution",
            args=[str(execution_id)],
            queue="source-processing",
        )
