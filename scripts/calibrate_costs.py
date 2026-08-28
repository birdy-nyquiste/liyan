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

A `--url` is a 来源 too, and the only way to measure what capturing one costs:
a fetch holds Chromium for as long as the page takes, which is the whole of a
URL 来源's cost and the thing the flat capture fee is meant to cover.

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


def submit_url(client: httpx.Client, url: str, timeout: float) -> tuple[str, str, str, int]:
    """One URL 来源, waited on before it can be confirmed.

    Unlike pasted text, a URL is not a 来源 until Chromium has been and returned,
    so this polls the preparation to `ready` first. What comes back also gives
    the character count the fit needs, which nobody knows before the fetch.
    """
    session_id = f"calibrate-{uuid.uuid4()}"
    created = client.post(
        "/task-creation/url-sources",
        json={
            "client_session_id": session_id,
            "client_source_id": "source-0",
            "url": url,
        },
    )
    created.raise_for_status()
    source_id = str(created.json()["id"])
    started = time.monotonic()
    body = ""
    while time.monotonic() - started < timeout:
        state = client.get(f"/task-creation/url-sources/{source_id}")
        state.raise_for_status()
        payload = state.json()
        status = str(payload.get("status", ""))
        if status in {"ready", "warning"}:
            body = str(payload.get("body") or "")
            break
        if status == "failure":
            raise SystemExit(f"Fetching {url} failed: {payload.get('failure_message')}")
        time.sleep(POLL_SECONDS)
    else:
        raise SystemExit(f"Fetching {url} did not finish inside {timeout}s.")
    confirmed = client.post(
        "/task-creation/confirm",
        json={
            "idempotency_key": session_id,
            "client_session_id": session_id,
            "source_ids": [source_id],
        },
    )
    confirmed.raise_for_status()
    payload = confirmed.json()
    return (
        session_id,
        str(payload["task"]["id"]),
        str(payload["source_revisions"][0]["id"]),
        len(body),
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
                 WHERE c.operation IN ('analyze_source', 'generate_article', 'fetch_url')
                 ORDER BY c.created_at
                """
            )
        ):
            provenance = record.provenance or ""
            name = provenance.removeprefix("calibration://")
            piece = sessions.get(name)
            if piece is None and record.operation in {"analyze_source", "fetch_url"}:
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


def deepseek_balance(api_key: str, base_url: str) -> dict[str, float] | None:
    """What DeepSeek says is left on the account, per currency.

    The only number in this whole system that comes from the provider as money
    rather than as tokens. `usage` reports tokens and `rate_card` turns them
    into dollars, and nothing has ever checked that arithmetic against what
    DeepSeek actually took — not the peak/off-peak split, not the assumption
    that `input_tokens` includes `cached_tokens`, not the claim that web search
    carries no separate fee. If any of those is wrong, every cost in
    `execution_costs` is wrong the same way, and silently.

    Every currency, not the one this script would prefer. An account carries a
    slot per currency and spends the one it was funded in: the account this was
    written against reads `USD 0.00` beside `CNY 10.07`, so picking USD would
    have reported that a batch of real runs cost nothing at all.

    `GET /user/balance` is account-wide and the only billing endpoint DeepSeek
    offers: there is no per-request cost, no usage history, and no lookup by
    response id. So this is a before-and-after on a quiet key, not an audit.
    """
    try:
        response = httpx.get(
            f"{base_url.rstrip('/')}/user/balance",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
        )
        response.raise_for_status()
        infos = response.json().get("balance_infos") or []
        return {str(info["currency"]): float(info["total_balance"]) for info in infos}
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        print(f"  (could not read the DeepSeek balance: {error!r})")
        return None


def reconcile(
    before: dict[str, float] | None,
    after: dict[str, float] | None,
    rows: list[Measured],
) -> None:
    """What the meter computed, against what the account actually lost.

    A close match is the only evidence available that the rate card is right.
    A gap says one of its assumptions is not, and which one is then worth
    hunting: a factor of about two points at the peak/off-peak window, and a
    factor of tens points at cache accounting.

    The rate card is quoted in USD, from DeepSeek's published USD price list.
    An account spending CNY is not being charged those numbers, and no CNY list
    is documented — so a CNY fall is reported as what it is and converted by
    nobody. Comparing it to the USD figure is a decision for whoever reads this,
    with today's rate in hand.
    """
    print("\nWhat DeepSeek actually charged")
    if before is None or after is None:
        print("  — no balance reading; set LIYAN_DEEPSEEK_API_KEY to reconcile.")
        return
    metered = sum(row.cost_micros for row in rows if row.cost_micros is not None) / 1e6
    unpriced = sum(1 for row in rows if row.cost_micros is None)
    print(f"  execution_costs total      {metered:.6f} USD over {len(rows)} run(s)")
    if unpriced:
        print(f"    — {unpriced} run(s) recorded no cost and are not in that total")

    moved = {
        currency: before.get(currency, 0.0) - amount
        for currency, amount in after.items()
        if abs(before.get(currency, 0.0) - amount) > 1e-9
    }
    if not moved:
        print("  account did not measurably fall.")
        print("  DeepSeek settles asynchronously: three live runs on 2026-08-28")
        print("  left the balance reading unchanged immediately afterwards. Read")
        print("  it again later rather than concluding the runs were free.")
        return
    for currency, spent in sorted(moved.items()):
        print(f"  account fell by            {spent:.6f} {currency}")
        if currency != "USD":
            print("    — the rate card is in USD and DeepSeek publishes no CNY list.")
            print("      Convert at today's rate before drawing a conclusion.")
            continue
        if spent <= 0:
            continue
        print(f"  meter / actual             {metered / spent:.2f}×")
        if not 0.8 <= metered / spent <= 1.25:
            print("    — off by more than a quarter. Suspect, in order: the")
            print("      peak/off-peak window (≈2×), cache accounting (≈30×), or")
            print("      a search fee this rate card says does not exist.")
    print("  This is account-wide. Anything else using the same key is in it too.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", required=True, help="One writer's access token.")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("LIYAN_DATABASE_URL", ""),
        help="Where the meter writes. Defaults to $LIYAN_DATABASE_URL.",
    )
    parser.add_argument("--corpus", type=Path, help="Directory of .txt/.md 来源.")
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        dest="urls",
        help="A URL 来源, repeatable. Measures what capturing one costs.",
    )
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument(
        "--deepseek-key",
        default=os.environ.get("LIYAN_DEEPSEEK_API_KEY", ""),
        help="Reconcile the meter against the real account balance.",
    )
    parser.add_argument(
        "--deepseek-base-url",
        default=os.environ.get("LIYAN_DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    parser.add_argument(
        "--articles",
        action="store_true",
        help="Also generate one 立言文章 per task, to measure that too.",
    )
    args = parser.parse_args(argv)

    if not args.database_url:
        parser.error("--database-url or LIYAN_DATABASE_URL is required to read the meter.")
    if not args.corpus and not args.urls:
        parser.error("Give --corpus, --url, or both.")
    pieces: list[Piece] = []
    if args.corpus:
        if not args.corpus.is_dir():
            parser.error(f"{args.corpus} is not a directory of corpus files.")
        pieces = read_corpus(args.corpus)
        if not pieces:
            parser.error(f"No .txt or .md files in {args.corpus}.")

    if pieces:
        print(f"{len(pieces)} pasted 来源, {min(p.characters for p in pieces):,}"
              f"–{max(p.characters for p in pieces):,} characters")
    if args.urls:
        print(f"{len(args.urls)} URL 来源")
    by_name: dict[str, Piece] = {piece.name: piece for piece in pieces}

    opening = (
        deepseek_balance(args.deepseek_key, args.deepseek_base_url)
        if args.deepseek_key
        else None
    )
    if opening:
        stated = ", ".join(f"{amount:.6f} {code}" for code, amount in sorted(opening.items()))
        print(f"DeepSeek balance before    {stated}")

    with _client(args.base_url, args.token) as client:
        for piece in pieces:
            _, task_id, revision_id = submit(client, piece)
            state = await_report(client, revision_id, args.timeout)
            print(f"  {piece.name:<30} 知言 {state}")
            if state == "succeeded" and args.articles:
                print(f"  {'':<30} 立言 {generate_article(client, task_id, args.timeout)}")
        for url in args.urls:
            _, task_id, revision_id, characters = submit_url(client, url, args.timeout)
            name = url
            by_name[name] = Piece(name=name, title=name, body="x" * characters)
            print(f"  {url[:29]:<30} fetched {characters:,} chars")
            state = await_report(client, revision_id, args.timeout)
            print(f"  {'':<30} 知言 {state}")
            if state == "succeeded" and args.articles:
                print(f"  {'':<30} 立言 {generate_article(client, task_id, args.timeout)}")

    rows = measured_costs(args.database_url, by_name)
    report(rows)
    closing = (
        deepseek_balance(args.deepseek_key, args.deepseek_base_url)
        if args.deepseek_key
        else None
    )
    reconcile(opening, closing, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
