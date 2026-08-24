"""Why one Execution ended the way it did.

The log says an Execution failed and names its code; the reason itself stays on
the row. That is deliberate — a provider's error text quotes whatever it was
handed, which here is 来源 bodies and article drafts, and `observability.py`
exists to keep such text out of logs that get shipped and retained.

So the detail is pulled rather than pushed: one Execution at a time, by someone
who has decided to look.

    .venv/bin/python scripts/explain_execution.py <execution-id>
    .venv/bin/python scripts/explain_execution.py --recent
"""

import argparse
import os
import sys
from typing import Any

import sqlalchemy
from sqlalchemy import text

RECENT = text(
    """
    SELECT id, operation, status, attempt, error_code, error_message,
           internal_error, created_at, started_at, finished_at
    FROM executions
    WHERE status IN ('failed', 'stale', 'cancelled')
    ORDER BY COALESCE(finished_at, created_at) DESC
    LIMIT :limit
    """
)

ONE = text(
    """
    SELECT id, operation, status, attempt, error_code, error_message,
           internal_error, created_at, started_at, finished_at
    FROM executions WHERE id = :execution_id
    """
)


def _database_url() -> str:
    url = os.environ.get("LIYAN_DATABASE_URL", "").strip()
    if not url:
        sys.exit("LIYAN_DATABASE_URL is not set. Source your .env first.")
    return url


def _show(row: Any) -> None:
    print(f"\n{row.operation}  attempt {row.attempt}  [{row.status}]")
    print(f"  id        {row.id}")
    print(f"  code      {row.error_code or '—'}")
    print(f"  told user {row.error_message or '—'}")
    print(f"  started   {row.started_at or '—'}")
    print(f"  finished  {row.finished_at or '—'}")
    print("  reason    " + (row.internal_error or "— (nothing recorded)"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("execution_id", nargs="?", help="the Execution to explain")
    parser.add_argument(
        "--recent",
        action="store_true",
        help="the last few that ended badly, when you do not have an id to hand",
    )
    parser.add_argument("--limit", type=int, default=5)
    arguments = parser.parse_args()

    if not arguments.execution_id and not arguments.recent:
        parser.error("give an execution id, or --recent")

    engine = sqlalchemy.create_engine(_database_url())
    try:
        with engine.connect() as connection:
            if arguments.recent:
                rows = connection.execute(RECENT, {"limit": arguments.limit}).all()
            else:
                rows = connection.execute(
                    ONE, {"execution_id": arguments.execution_id}
                ).all()
            if not rows:
                print("Nothing matched.")
                return
            for row in rows:
                _show(row)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
