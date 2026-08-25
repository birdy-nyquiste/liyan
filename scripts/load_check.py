"""What one worker slot actually carries, measured rather than guessed.

`LIYAN_MAX_ACTIVE_EXECUTIONS_PER_USER` is a number somebody has to choose, and
the only honest way to choose it is to watch the system under the load the
launch expects. This drives that load: N writers, each creating a 立言任务 from
pasted 来源 and waiting for every 知言报告, all at once, against a stack that is
actually running — Local with `docker compose` and a worker, or Staging.

It reads and writes real data through the real API, so it is never pointed at
Production. Every task it creates is left behind deliberately: what the run
cost is visible afterwards, and deleting on the way out would hide a failure
that happened at the end.

    .venv/bin/python scripts/load_check.py \\
        --base-url http://localhost:8000 \\
        --token "$STAGING_ACCESS_TOKEN" --token "$SECOND_ACCESS_TOKEN" \\
        --sources 3 --timeout 600

One token is one writer, because the ceiling being measured is per user: two
writers with one token is a different experiment from two writers.

What it prints is what a launch decision needs — how long a 知言报告 took at the
median and at the worst, how many runs never finished inside the timeout, and
how many requests the ceiling refused. A refusal is not a fault here: it is the
ceiling doing its job, and its count against the wait time is the trade the
number encodes.
"""

import argparse
import statistics
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import httpx

BODY = "英国2022年的四天工作制试验已经证明了显著效果。" * 40
POLL_SECONDS = 3.0


@dataclass(frozen=True)
class Writer:
    """One simulated writer, and everything their journey needs."""

    label: str
    base_url: str
    token: str
    sources: int
    timeout: float


@dataclass
class WriterOutcome:
    """What one simulated writer's whole journey did."""

    label: str
    report_seconds: list[float] = field(default_factory=list)
    refusals: int = 0
    unfinished: int = 0
    error: str | None = None


def _sources(client: httpx.Client, session_id: str, count: int) -> list[str]:
    source_ids: list[str] = []
    for index in range(count):
        response = client.post(
            "/task-creation/pasted-sources",
            json={
                "client_session_id": session_id,
                "client_source_id": f"source-{index}",
                "title": f"四天工作制 {session_id}-{index}",
                "body": BODY,
                "provenance": f"https://press.example/{session_id}/{index}",
            },
        )
        response.raise_for_status()
        source_ids.append(str(response.json()["id"]))
    return source_ids


def _confirm(
    client: httpx.Client, session_id: str, source_ids: Sequence[str]
) -> tuple[str, list[str]] | None:
    """Confirm the session, or report that the ceiling refused it."""
    response = client.post(
        "/task-creation/confirm",
        json={
            "idempotency_key": session_id,
            "client_session_id": session_id,
            "source_ids": list(source_ids),
        },
    )
    if response.status_code == 429:
        return None
    response.raise_for_status()
    payload = response.json()
    return (
        str(payload["task"]["id"]),
        [str(revision["id"]) for revision in payload["source_revisions"]],
    )


def _await_reports(
    client: httpx.Client,
    revision_ids: Sequence[str],
    *,
    started_at: float,
    timeout: float,
    outcome: WriterOutcome,
) -> None:
    """Poll each 知言 run to a terminal state, timing the ones that finish.

    Polling rather than pushing, because that is what the workbench does: the
    load this measures includes the reads, not only the runs.
    """
    pending = list(revision_ids)
    while pending and time.monotonic() - started_at < timeout:
        for revision_id in list(pending):
            response = client.get(f"/source-revisions/{revision_id}/zhiyan")
            response.raise_for_status()
            state = str(response.json()["status"])
            if state in {"succeeded", "failed", "cancelled"}:
                pending.remove(revision_id)
                outcome.report_seconds.append(time.monotonic() - started_at)
        if pending:
            time.sleep(POLL_SECONDS)
    outcome.unfinished += len(pending)


def _run_writer(writer: Writer) -> WriterOutcome:
    outcome = WriterOutcome(label=writer.label)
    headers = {"Authorization": f"Bearer {writer.token}"}
    try:
        with httpx.Client(base_url=writer.base_url, headers=headers, timeout=30.0) as client:
            session_id = f"load-{writer.label}"
            source_ids = _sources(client, session_id, writer.sources)
            started_at = time.monotonic()
            confirmed = _confirm(client, session_id, source_ids)
            if confirmed is None:
                outcome.refusals += 1
                return outcome
            _await_reports(
                client,
                confirmed[1],
                started_at=started_at,
                timeout=writer.timeout,
                outcome=outcome,
            )
    except httpx.HTTPError as error:
        outcome.error = repr(error)
    return outcome


def _report(outcomes: Sequence[WriterOutcome], wall_seconds: float) -> int:
    """Print what the run measured, and say whether it proved anything."""
    finished = [seconds for outcome in outcomes for seconds in outcome.report_seconds]
    refusals = sum(outcome.refusals for outcome in outcomes)
    unfinished = sum(outcome.unfinished for outcome in outcomes)
    errors = [outcome for outcome in outcomes if outcome.error]

    print(f"writers            {len(outcomes)}")
    print(f"wall clock         {wall_seconds:.1f}s")
    print(f"知言报告 finished    {len(finished)}")
    if finished:
        ordered = sorted(finished)
        print(f"  median           {statistics.median(ordered):.1f}s")
        print(f"  slowest          {ordered[-1]:.1f}s")
    print(f"知言 unfinished      {unfinished}")
    print(f"refused at ceiling {refusals}")
    for outcome in errors:
        print(f"error {outcome.label}: {outcome.error}")

    if errors:
        return 1
    if not finished:
        print("\nNothing finished. A worker that is not running looks exactly like this.")
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="The API to load, never Production.")
    parser.add_argument(
        "--token",
        action="append",
        required=True,
        dest="tokens",
        help="One access token per simulated writer; repeat the flag.",
    )
    parser.add_argument("--sources", type=int, default=3, help="来源 per 立言任务 (1-3).")
    parser.add_argument(
        "--timeout", type=float, default=600.0, help="Seconds to wait for one writer's reports."
    )
    arguments = parser.parse_args(argv)

    if not 1 <= arguments.sources <= 3:
        parser.error("A 任务版本 holds one to three 来源.")

    writers = [
        Writer(
            label=f"writer-{index}",
            base_url=arguments.base_url,
            token=token,
            sources=arguments.sources,
            timeout=arguments.timeout,
        )
        for index, token in enumerate(arguments.tokens)
    ]

    started_at = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(writers)) as pool:
        outcomes = list(pool.map(_run_writer, writers))
    return _report(outcomes, time.monotonic() - started_at)


if __name__ == "__main__":
    sys.exit(main())
