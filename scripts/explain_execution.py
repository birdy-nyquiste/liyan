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

from liyan_server.settings import Settings

RECENT = text(
    """
    SELECT id, operation, status, attempt, error_code, error_message,
           internal_error, stale_result, created_at, started_at, finished_at
    FROM executions
    WHERE status IN ('failed', 'stale', 'cancelled')
    ORDER BY COALESCE(finished_at, created_at) DESC
    LIMIT :limit
    """
)

ONE = text(
    """
    SELECT id, operation, status, attempt, error_code, error_message,
           internal_error, stale_result, created_at, started_at, finished_at
    FROM executions WHERE id = :execution_id
    """
)


def _database_url() -> str:
    """Read it the way the server does, so the same rules apply.

    Going to the environment directly would skip the driver rewrite in
    `Settings`, and this script would then fail against a managed database in
    exactly the way the server no longer does — which is the moment somebody
    most needs it to work.
    """
    if not os.environ.get("LIYAN_DATABASE_URL", "").strip():
        sys.exit("LIYAN_DATABASE_URL is not set. Source your .env first.")
    return Settings().database_url


def _show(row: Any) -> None:
    print(f"\n{row.operation}  attempt {row.attempt}  [{row.status}]")
    print(f"  id        {row.id}")
    print(f"  code      {row.error_code or '—'}")
    print(f"  told user {row.error_message or '—'}")
    print(f"  started   {row.started_at or '—'}")
    print(f"  finished  {row.finished_at or '—'}")
    print("  reason    " + (row.internal_error or "— (nothing recorded)"))
    _show_refused(row)


#: How much of a refused report to print. Enough to see how it opens, which is
#: where a malformed one goes wrong — a `JSONDecodeError` at character zero is
#: answered by the first line and by nothing after it. The whole of it is on the
#: row for anyone who wants the rest.
REFUSED_PREVIEW = 2_000


def _show_refused(row: Any) -> None:
    """What the provider actually returned, when it returned something unusable.

    The code says which rule the output broke. Only the output says why, and
    without it a recurring rejection is a dead end: three local runs failed
    `invalid_report_schema` with `JSONDecodeError` at character zero, and no
    part of the record said whether the model had written prose, a fence this
    adapter does not unwrap, or nothing recognisable at all.

    Printed here rather than logged, for the reason this whole script exists:
    the text quotes 来源 bodies back, and that must not reach shipped logs.
    """
    refused = row.stale_result
    if not isinstance(refused, dict):
        return
    text_key = next(
        (key for key in ("report_text", "article_text") if isinstance(refused.get(key), str)),
        None,
    )
    if text_key is None:
        return
    body: str = refused[text_key]
    searches = refused.get("search_actions")
    if isinstance(searches, list):
        opened = [action.get("url") for action in searches if isinstance(action, dict)]
        print(f"  searched  {len(searches)} action(s), {len([u for u in opened if u])} opened")
    print(f"  returned  {len(body)} characters, refused:")
    for line in body[:REFUSED_PREVIEW].splitlines() or [""]:
        print(f"      | {line}")
    if len(body) > REFUSED_PREVIEW:
        print(f"      | … {len(body) - REFUSED_PREVIEW} more characters on the row")


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
