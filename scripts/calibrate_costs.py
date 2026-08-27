"""What a 知言 run and a 立言 generation actually cost, measured rather than assumed.

`docs/operations/credits.md` prices this product from five assumptions — how
many tokens a Chinese character becomes, how large the instruction and schema
preamble is, how much text DeepSeek injects when it searches, how long a
知言报告 comes out, and how long an article does. Every 额度 figure on that page
rests on them, and none of them has been measured. This is how they stop being
assumptions.

It does not wait for real traffic. Behind an allowlist there is barely any, and
what there is would be whatever a handful of testers happened to paste — a
biased sample, slowly. Driving a corpus you chose gives the same answer in an
afternoon, over a spread you control.

    .venv/bin/python scripts/calibrate_costs.py \\
        --base-url http://localhost:8000 \\
        --token "$ACCESS_TOKEN" \\
        --corpus ./calibration-corpus \\
        --articles

It writes through the real API, so the whole path is exercised and the numbers
come from the same meter production will bill from. It reads the results
straight from `execution_costs`, because that is where the meter writes and
there is no endpoint for it — nor should there be, for an operator's tool.

Real data through the real API, so this is pointed at Local or Staging and never
at Production. Every task is left behind on purpose: the rows are the output.

## What makes a corpus worth running

One file per 来源, `.txt` or `.md`, and **the material you actually expect**.
Synthetic text gives synthetic answers: repetitive filler tokenizes unlike
prose, and a passage making no checkable claims gives 知言 nothing to search
for, which is precisely the term least understood here.

Spread it deliberately — a few hundred characters to the 500,000 `limits.md`
allows, Chinese and English, dense-with-claims and discursive. The fit below is
a line through these points, so points at one end only give a line through one
end only.
"""

import argparse
import os
import statistics
import sys
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx
import sqlalchemy
from sqlalchemy import text as sql

POLL_SECONDS = 5.0
CORPUS_SUFFIXES = {".txt", ".md", ".markdown"}


@dataclass(frozen=True)
class Piece:
    """One corpus file, and the 来源 it becomes."""

    name: str
    title: str
    body: str

    @property
    def characters(self) -> int:
        return len(self.body)


@dataclass
class Measured:
    """One run's cost, beside the 来源 length that ought to predict it."""

    operation: str
    piece: str
    characters: int
    input_tokens: int | None
    cached_input_tokens: int | None
    output_tokens: int | None
    search_calls: int | None
    worker_milliseconds: int | None
    cost_micros: int | None
    charge_credits: int | None


def read_corpus(directory: Path) -> list[Piece]:
    pieces: list[Piece] = []
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in CORPUS_SUFFIXES or not path.is_file():
            continue
        body = path.read_text(encoding="utf-8").strip()
        if not body:
            continue
        pieces.append(Piece(name=path.name, title=path.stem[:200], body=body))
    return pieces


def _client(base_url: str, token: str) -> httpx.Client:
    return httpx.Client(
        base_url=base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=60.0,
    )


def submit(client: httpx.Client, piece: Piece) -> tuple[str, str, str]:
    """One 来源 in a 立言任务 of its own.

    One per task deliberately: a task holding three would analyze three at once
    and leave every measurement sharing a worker with two others, which is a
    throughput experiment rather than a cost one. `load_check.py` is where
    contention belongs.
    """
    session_id = f"calibrate-{uuid.uuid4()}"
    created = client.post(
        "/task-creation/pasted-sources",
        json={
            "client_session_id": session_id,
            "client_source_id": "source-0",
            "title": piece.title,
            "body": piece.body,
            "provenance": f"calibration://{piece.name}",
        },
    )
    created.raise_for_status()
    confirmed = client.post(
        "/task-creation/confirm",
        json={
            "idempotency_key": session_id,
            "client_session_id": session_id,
            "source_ids": [str(created.json()["id"])],
        },
    )
    if confirmed.status_code == 429:
        raise SystemExit(
            "The per-user ceiling refused this submission. Calibration is not a load "
            "test — run it with nothing else in flight, or raise "
            "LIYAN_MAX_ACTIVE_EXECUTIONS_PER_USER for the run."
        )
    confirmed.raise_for_status()
    payload = confirmed.json()
    return (
        session_id,
        str(payload["task"]["id"]),
        str(payload["source_revisions"][0]["id"]),
    )


def await_report(client: httpx.Client, revision_id: str, timeout: float) -> str:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        response = client.get(f"/source-revisions/{revision_id}/zhiyan")
        response.raise_for_status()
        state = str(response.json()["status"])
        if state in {"succeeded", "failed", "cancelled"}:
            return state
        time.sleep(POLL_SECONDS)
    return "unfinished"


def generate_article(client: httpx.Client, task_id: str, timeout: float) -> str:
    started = client.post(
        f"/tasks/{task_id}/liyan-runs",
        json={"idempotency_key": f"calibrate-{uuid.uuid4()}"},
    )
    if started.status_code >= 400:
        return f"refused ({started.status_code})"
    began = time.monotonic()
    while time.monotonic() - began < timeout:
        state = client.get(f"/tasks/{task_id}/liyan")
        state.raise_for_status()
        status = str(state.json().get("run", {}).get("status", "unknown"))
        if status in {"succeeded", "failed", "cancelled"}:
            return status
        time.sleep(POLL_SECONDS)
    return "unfinished"


def measured_costs(database_url: str, sessions: dict[str, Piece]) -> list[Measured]:
    """Every cost this run produced, joined back to the 来源 that caused it.

    Matched through the 来源's provenance, which carries the corpus file name:
    the alternative is trusting that nothing else touched the database while
    this ran, and a calibration that quietly measured somebody else's afternoon
    would be worse than no calibration.
    """
    engine = sqlalchemy.create_engine(database_url)
    rows: list[Measured] = []
    with engine.connect() as connection:
        for record in connection.execute(
            sql(
                """
                SELECT c.operation, c.input_tokens, c.cached_input_tokens,
                       c.output_tokens, c.search_calls, c.worker_milliseconds,
                       c.cost_micros, c.charge_credits, r.provenance
                  FROM execution_costs c
                  JOIN executions e ON e.id = c.execution_id
                  LEFT JOIN source_revisions r ON r.id = e.target_id
                 WHERE c.operation IN ('analyze_source', 'generate_article')
                 ORDER BY c.created_at
                """
            )
        ):
            provenance = record.provenance or ""
            name = provenance.removeprefix("calibration://")
            piece = sessions.get(name)
            if piece is None and record.operation == "analyze_source":
                continue
            rows.append(
                Measured(
                    operation=record.operation,
                    piece=name or "—",
                    characters=piece.characters if piece else 0,
                    input_tokens=record.input_tokens,
                    cached_input_tokens=record.cached_input_tokens,
                    output_tokens=record.output_tokens,
                    search_calls=record.search_calls,
                    worker_milliseconds=record.worker_milliseconds,
                    cost_micros=record.cost_micros,
                    charge_credits=record.charge_credits,
                )
            )
    engine.dispose()
    return rows


def fit(points: Sequence[tuple[float, float]]) -> tuple[float, float] | None:
    """Least squares through (来源 characters, tokens).

    The slope is how many tokens a character becomes; the intercept is
    everything that does not scale with length — the instruction and schema
    preamble, plus whatever the provider injected when it searched. Separating
    them is the whole reason a corpus has to be spread across lengths: points
    clustered at one length fix a slope no better than a single point does.
    """
    if len(points) < 3:
        return None
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    variance = sum((x - mean_x) ** 2 for x in xs)
    if variance == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / variance
    return slope, mean_y - slope * mean_x


def _cell(value: object) -> str:
    return "—" if value is None else f"{value:,}" if isinstance(value, int) else str(value)


def report(rows: list[Measured]) -> None:
    analyses = [row for row in rows if row.operation == "analyze_source"]
    articles = [row for row in rows if row.operation == "generate_article"]

    print("\n知言 runs")
    print(f"{'来源':<24}{'chars':>9}{'input':>10}{'cached':>9}{'output':>9}"
          f"{'search':>8}{'µUSD':>10}{'额度':>7}")
    for row in sorted(analyses, key=lambda item: item.characters):
        print(
            f"{row.piece[:23]:<24}{row.characters:>9,}{_cell(row.input_tokens):>10}"
            f"{_cell(row.cached_input_tokens):>9}{_cell(row.output_tokens):>9}"
            f"{_cell(row.search_calls):>8}{_cell(row.cost_micros):>10}"
            f"{_cell(row.charge_credits):>7}"
        )

    unmetered = [row for row in analyses if row.input_tokens is None]
    if unmetered:
        print(
            f"\n  {len(unmetered)} of {len(analyses)} runs reported no usage. If that is all "
            "of them,\n  the provider's block is not shaped the way `provider_usage` expects "
            "— which is\n  the first thing this run exists to find out."
        )

    priced = [row for row in analyses if row.input_tokens is not None]
    if priced:
        input_fit = fit([(row.characters, row.input_tokens or 0) for row in priced])
        output_fit = fit([(row.characters, row.output_tokens or 0) for row in priced])
        print("\nWhat the assumptions in credits.md come to")
        if input_fit:
            slope, intercept = input_fit
            print(f"  characters → input tokens   {slope:.3f} per char   (assumed 0.6)")
            print(f"  fixed input per run         {intercept:,.0f} tokens")
            print("    — preamble plus search injection, which credits.md")
            print("      assumes to be about 2,000 + 15,000 = 17,000")
        if output_fit:
            slope, intercept = output_fit
            print(f"  output tokens               {intercept:,.0f} + {slope:.3f} per char")
            print("    — credits.md assumes a flat ~4,000 for a 知言报告")
        searches = [row.search_calls for row in priced if row.search_calls is not None]
        if searches:
            print(f"  searches per run            median {statistics.median(searches):.0f}, "
                  f"max {max(searches)}")
        credits = [row.charge_credits for row in priced if row.charge_credits]
        if credits:
            print(f"  额度 per 知言 run             median {statistics.median(credits):.0f}, "
                  f"range {min(credits)}–{max(credits)}   (credits.md: 28 short, 297 long)")

    if articles:
        print("\n立言 runs")
        for row in articles:
            print(
                f"  input {_cell(row.input_tokens)}  output {_cell(row.output_tokens)}  "
                f"{_cell(row.cost_micros)} µUSD  {_cell(row.charge_credits)} 额度"
            )
        article_credits = [row.charge_credits for row in articles if row.charge_credits]
        if article_credits:
            print(f"  额度 per article             median "
                  f"{statistics.median(article_credits):.0f}   (credits.md: 25)")

    print(
        "\nRecord the answers in docs/operations/credits.md, and replace its "
        "assumptions\ntable with them. Until that happens the page is reasoned "
        "rather than measured,\nand it says so."
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", required=True, help="One writer's access token.")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("LIYAN_DATABASE_URL", ""),
        help="Where the meter writes. Defaults to $LIYAN_DATABASE_URL.",
    )
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument(
        "--articles",
        action="store_true",
        help="Also generate one 立言文章 per task, to measure that too.",
    )
    args = parser.parse_args(argv)

    if not args.database_url:
        parser.error("--database-url or LIYAN_DATABASE_URL is required to read the meter.")
    if not args.corpus.is_dir():
        parser.error(f"{args.corpus} is not a directory of corpus files.")
    pieces = read_corpus(args.corpus)
    if not pieces:
        parser.error(f"No .txt or .md files in {args.corpus}.")

    print(f"{len(pieces)} 来源, {min(p.characters for p in pieces):,}"
          f"–{max(p.characters for p in pieces):,} characters")
    by_name = {piece.name: piece for piece in pieces}

    with _client(args.base_url, args.token) as client:
        for piece in pieces:
            _, task_id, revision_id = submit(client, piece)
            state = await_report(client, revision_id, args.timeout)
            print(f"  {piece.name:<30} 知言 {state}")
            if state == "succeeded" and args.articles:
                print(f"  {'':<30} 立言 {generate_article(client, task_id, args.timeout)}")

    report(measured_costs(args.database_url, by_name))
    return 0


if __name__ == "__main__":
    sys.exit(main())
