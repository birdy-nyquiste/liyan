from datetime import UTC, datetime

from liyan_server.database import Task


def record_task_activity(task: Task, *, at: datetime | None = None) -> None:
    """Move a task in recent-work navigation for an agreed meaningful action."""
    task.last_activity_at = at or datetime.now(UTC)
