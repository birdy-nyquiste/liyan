# 异步工作：Execution、队列、worker

Everything in 立言阁 that takes longer than a request — fetching a URL, parsing a
file, a 知言 analysis, a 主题知言 analysis, 提炼主题, generating a 立言文章,
submitting a Blog Preview — runs through one mechanism. This page is that
mechanism: what a unit of work is, where it is sent, which process receives it,
what may happen to it, and what notices when nothing does.

It is written because the mechanism is real and was nowhere visible: its parts
each explain themselves well in their own module, and no page said how they fit.
The numbers it runs into belong to `docs/operations/limits.md`, what work costs
belongs to `docs/operations/credits.md`, and neither is restated here.

## One abstraction: the Execution

Every unit of asynchronous work is one row in `executions`.

**The queue carries an Execution's identity and nothing else.** No business
content is ever at rest in the broker; a worker receives an id and reads from
the database what that run was approved to do. So the database is the single
source of truth about work, and the queue is only how somebody is told to look.

A row carries:

| Field | What it is for |
| --- | --- |
| `owner_id` | Whose work it is. Every limit and every charge is per user. |
| `operation` | Which of the seven kinds of work this is. |
| `target_type`, `target_id` | What it acts on. **No foreign key**: the target is a 来源准备行, a 来源 Revision, an article, a 主题 snapshot, or a 发布任务, and one column cannot reference five tables. |
| `input_version`, `attempt` | Which input, and which try at it. |
| `input_identity` | A digest of the approved input, so two runs of the same thing are recognisable. |
| `input_snapshot` | Everything this run was approved to send: model, Prompt version, content hash, tool policy, the moment it was requested. |
| `status` | Where it is in the state machine below. |
| `trace_id` | One identity across the logs of a run. |
| `error_code`, `error_message` | Why it ended, and the one sentence the user reads. |
| `internal_error` | Why it *really* ended. Never returned to a client. |
| `retry_allowed_at` | The earliest moment a new run for this target may start. Server-owned. |
| `result_id` | The business content it produced, if any. |
| `stale_result` | Provider output that arrived too late or was refused. Kept for tracing; never becomes business content. |
| `idempotency_key` | What makes a repeated client request return the first answer instead of doing the work twice. |

## Seven operations

| operation | Target | Result lands in | Queue |
| --- | --- | --- | --- |
| `fetch_url` | `source_preparation` | `url_fetch_results` | source-processing |
| `parse_file` | `source_preparation` | `file_parse_results` | source-processing |
| `analyze_source` | `source_revision` | `zhiyan_reports` | provider-runs |
| `analyze_theme` | `theme_revision` | `theme_reports` | provider-runs |
| `propose_themes` | `theme_proposal` | `theme_proposals.candidates` | provider-runs |
| `generate_article` | `liyan_article` | `liyan_run_results` | provider-runs |
| `publish_preview` | `publish_task` | `publish_tasks` | provider-runs |

## Two queues, split by what work costs a machine

Not by what it means. `execution_dispatch.py` owns the mapping and both names,
and is imported by both sides — a producer that sends where no consumer listens
fails in the quietest way available.

**`source-processing`** — Chromium and the file parsers. Prefork,
`--concurrency=1`, `--max-tasks-per-child=8`. A fully imported copy of this
application is roughly 110MB and a URL fetch launches a browser beside it, on an
instance with 512MB; hence one slot, and hence recycling the process so a
browser that does not release everything cannot accumulate across a day.

**`provider-runs`** — everything whose time is spent waiting on somebody else's
server. Threads, `--concurrency=4`. Threads rather than prefork is the whole
point: prefork at four would be four interpreters, and what this work actually
is, is four blocked sockets.

The split exists because these were once one queue, and the mis-sizing was at
the centre of it: **a memory budget was throttling a network wait.** A 知言 run —
two to three minutes on a socket, no meaningful memory, no CPU — was holding the
single slot that exists only because of Chromium.

An operation absent from the mapping goes to the heavy queue, and Celery's
`task_default_queue` points there too. That is the conservative answer: a new
operation running slowly beside Chromium is a worse day than a crash, and a
better one than an unbounded number of them sharing an interpreter.

## Four processes

`render.yaml` describes one environment; Staging and Production are two separate
deployments of it with their own names and secrets.

- **`liyan-api`** — FastAPI. Runs `alembic upgrade head` as a *pre-deploy*, not
  in the build: a build has no guaranteed route to the private database and runs
  even for a deploy that is then cancelled, which would leave the schema ahead
  of the code serving traffic.
- **`liyan-worker-heavy`** — consumes `source-processing`. The only process that
  installs Chromium.
- **`liyan-worker-provider`** — consumes `provider-runs`. No browser.
- **`liyan-beat`** — schedules what nobody triggers. It never executes a task.

Both workers name their queue with `-Q` explicitly. Left off, the heavy worker
would also consume `provider-runs` and the split would buy nothing while looking
like it had.

Deploy order matters, one way round only: bring up the provider worker first,
consuming a queue nothing routes to yet, and deploy the API after. The reverse
strands every provider run on a queue with no consumer, and nothing reports it.
No drain is needed at cutover, for the reason in the next section.

## The path one run takes

1. **The API creates the Execution** inside the transaction that admits the
   work, and commits. 知言 is the deliberate exception: its 预扣 is taken inside
   that transaction, but its runs are queued *after* the commit, because a 知言
   failure must never roll back the 任务版本 that was just created.
2. **`dispatcher.dispatch(execution_id, operation)`** sends
   `liyan.process_execution` to `queue_for(operation)`. The operation is passed
   rather than looked up: the caller is holding the row it just wrote, and a
   dispatcher that had to read the database would turn one insert into two round
   trips on the hot path of every submission.
3. **The worker's `process_execution` reads the row's `operation`** and branches
   to the handler for it — **branching on the row, never on which queue
   delivered it.** That is what lets work queued before a routing change still
   run, and why a queue split needs no drain.
4. **Every handler has the same shape**: *claim* the run (`queued` → `running`,
   after checking the approved input snapshot still matches what is in the
   database), call the provider, admit the answer only through deterministic
   acceptance, and write business content only if nobody has given up on this
   run meanwhile. Then record what it cost, whatever became of it.

If dispatch itself fails, the run is failed visibly with `dispatch_failed` and
`retry_allowed_at` set to now — rather than sitting `queued` forever behind a
broker nobody can reach.

## States, and who may write

    queued → running → succeeded | failed | cancelled | stale
                ↑
        cancel_requested

`queued`, `running` and `cancel_requested` are **active**. The other four are
**terminal**, and `surrendered()` is the word for them: every worker refuses to
write to a run that is already terminal. A cancellation is a *request* — the
worker honours it at its next checkpoint, which can be a whole provider call
away — so the row records the request and the interface says 正在终止 rather than
pretending the work stopped.

A provider answer that arrives after somebody else ended the run becomes
`stale`: kept verbatim in `stale_result` for tracing, charged as a cost, and
never allowed to overwrite current business data.

## Three database rules instead of check-then-act

- `unique(target_id, input_version, attempt)`
- a partial unique index over `status IN ('queued','running','cancel_requested')`
  keyed on `target_id` — **one active run per target is a database rule**, so two
  concurrent requests cannot both pass a check and both queue
- `unique(owner_id, operation, idempotency_key)`

## Retry, and who owns the timing

`zhiyan/recovery.py` is the whole policy, and holds no database or transport
dependency so the rule stays one readable place.

- The initial operation gets **at most two runs**: the first, plus one automatic
  attempt created only when the failure was one another identical run could
  plausibly survive. A missing API key, an input that is gone, an unreachable
  queue — none of them spend it.
- Every later run is a **manual retry**, at most two in any rolling 30 minutes
  per target. Cancelling does not refund the call it made.
- **The server decides when.** Backoff is written onto `retry_allowed_at`; a
  client may only count down to it, and a request that arrives early is refused
  429 with `Retry-After`.

## What notices when nothing happens

A dead worker is the quietest failure this system has: nothing raises, the API
keeps answering, and every piece of work a user starts simply waits forever.
Three scheduled jobs exist for that.

- **`recover_stalled_executions`** (every 5 minutes) ends runs nobody came back
  from, and distinguishes two causes with two codes: `worker_lost` (30 minutes
  `running` in silence — a deploy, an OOM kill, a lost machine) and
  `worker_never_started` (30 minutes `queued` unclaimed — a lost message, or a
  queue no worker consumes; the fix is a worker or a routing name, not a
  process). It guesses **once** and never reopens a run, because a late answer
  from a merely slow worker is refused anyway. Credit reconciliation runs
  immediately after, so a run this sweep just gave up on has its 预扣 settled
  now rather than a whole interval later.
- **`clean_expired_data`** (hourly) collects what retention says to, and forgets
  workers that are gone rather than unwell — a renamed or removed worker leaves
  a heartbeat row that can never beat again, and readiness would otherwise
  report `silent` forever, naming a process that no longer exists.
- **`ping`** (one per queue) exists because **a heartbeat must not be a function
  of demand.** Heartbeats are written on the way into each run — a worker that
  is processing is by definition alive — which worked while one worker did
  everything and was rarely idle. `source-processing` now genuinely idles for
  hours, and a perfectly healthy worker would report `silent`. So beat gives each
  queue something to do.

Heartbeats land in `worker_heartbeats`; `/health/ready` reports `beating`,
`silent`, or `unknown`, taking the worst of every row. **Beat cannot write its
own row** — it only schedules — so the worker that runs a scheduled task writes
`liyan-beat` on its behalf. A scheduled task arriving at all is the only evidence
beat is alive.

## Two refusals at the entry, deliberately not one

- **`execution_limits` → 429.** This user is already holding too much of a
  shared queue (six active Executions by default). Waiting fixes it.
- **`credit_limits` → 402.** They cannot pay for what they are starting. A
  purchase fixes it, and `Retry-After` would name a moment at which nothing will
  have changed.

Folding them together would tell a user to wait for something waiting cannot
fix. Both are called at the entry points that start work rather than wired in as
a dependency, because the entry points disagree about when to ask: an idempotent
replay must never be refused — the runs it repeats are exactly what put its user
at the ceiling — and saving a 来源编辑会话 is outside the ceiling entirely, since
refusing it would discard editing work rather than delay work being started.

The ceiling is asked per *act*, not per Execution: confirming a 任务创建会话 with
three 来源 queues three 知言 runs from one act, and refusing the fourth halfway
would leave a 任务版本 with some 来源 analysed and some not, for a reason the user
never chose. A batch admitted under the ceiling is admitted whole.

## Cost is recorded for every terminal outcome

`metering.record_execution_cost` writes one row per Execution — including the
failed, cancelled and superseded ones, because the provider invoiced those just
the same. `TOKEN_METERED_OPERATIONS` are the ones whose cost is dominated by a
provider call, so a missing `usage` leaves their cost *unknown* rather than zero;
`FLAT_CHARGED_OPERATIONS` (capture) are charged a fee known before they run. Only
a chargeable outcome becomes a charge: work that produced nothing is free however
much it cost.

## The same code, in tests

Two seams and no more are substituted, so a test drives the real application:

- **`RecordingDispatcher`** holds queued Executions so a test decides when each
  one runs. That is what makes partial progress observable — three 来源 with two
  reports in and one still running is a state a test can be *in*.
- **`InlineDispatcher`** (`scripts/e2e_server.py`) runs each Execution on a
  background thread the moment it is queued, so a browser sees exactly the
  transitions it sees in production, without a broker.

Neither replaces a domain rule, a worker, or the database.
