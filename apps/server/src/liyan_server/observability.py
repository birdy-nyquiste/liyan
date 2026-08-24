"""One JSON object per log line, carrying identities and nothing else.

立言阁 handles 来源 bodies, 知言报告, user instructions, articles, and the Blog
ingest credential. None of that belongs in a log, at any level, on any
environment — logs are shipped, retained, and read by people and services that
have no business with the content.

So the rule is an allowlist. A field nobody has vouched for is dropped and its
*name* recorded, rather than the formatter guessing whether a value is safe.
That way the next field somebody attaches to a log call cannot leak by being
unanticipated: it is excluded until someone adds it here on purpose.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

#: Fields a log line may carry. Every one is an identity, a state, a code, or a
#: count — nothing a user wrote and nothing that authenticates anybody.
SAFE_FIELDS: frozenset[str] = frozenset(
    {
        # Who and what, so a line can be joined to the work it describes.
        "trace_id",
        "execution_id",
        "task_id",
        "source_id",
        "owner_id",
        "cleanup_run_id",
        # What happened.
        "operation",
        "status",
        "attempt",
        "error_code",
        # Operational shape: configuration names and counts, never their values.
        "targets",
        "missing",
        "affects",
        "object_storage",
        "expired_task_creation_sources",
        "expired_source_edit_sessions",
        "purged_tasks",
        "removed_objects",
        "stalled_executions",
        "worker",
    }
)

_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "msg",
        "message",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class JsonLogFormatter(logging.Formatter):
    """Renders a record as one JSON object, keeping only allowlisted fields."""

    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        dropped: list[str] = []
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            if key in SAFE_FIELDS:
                line[key] = value
            else:
                dropped.append(key)
        if dropped:
            # Names only. Saying what was withheld keeps an omission visible
            # without putting the reason for withholding it into the log.
            line["dropped_fields"] = dropped
        if record.exc_info and record.exc_info[0] is not None:
            # The type, never the message: an exception string routinely quotes
            # whatever it was handed, which here is business content.
            line["exception"] = record.exc_info[0].__name__
        return json.dumps(line, ensure_ascii=False, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Send every log line through the JSON formatter, once.

    Both the API and the worker call this at import, and a test suite imports
    both, so configuring twice must not double every line.
    """
    root = logging.getLogger()
    if not any(isinstance(h.formatter, JsonLogFormatter) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        root.handlers = [handler]
        root.setLevel(level)
    _reclaim(UVICORN_LOGGERS)


#: Uvicorn installs handlers of its own before the application is imported, and
#: they do not propagate. Its access line carries the raw request target —
#: query string included — so left alone it would ship unstructured and
#: unfiltered beside everything this module is careful about.
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _reclaim(names: tuple[str, ...]) -> None:
    for name in names:
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True


def log_execution_failed(
    *, execution_id: object, operation: str, attempt: int, error_code: str | None
) -> None:
    """Say that a run ended badly, and which row explains it.

    Workers record the reason on the Execution and used to log nothing, which
    left whoever was watching three terminals with a source that turned red and
    no thread to pull.

    The reason itself stays on the row rather than joining the log line. A
    provider's error text quotes whatever it was handed, and this module's whole
    premise is that such text never reaches a log. `internal_error` is read
    deliberately, one execution at a time, by someone who has decided to look:

        scripts/explain_execution.py <execution-id>
    """
    logging.getLogger("liyan_server.executions").warning(
        "execution_failed",
        extra={
            "execution_id": str(execution_id),
            "operation": operation,
            "attempt": attempt,
            "error_code": error_code,
        },
    )
