# Scaling

`limits.md` opens with the premise everything else in it follows from: **one
worker slot**. This page is how that stops being true, in what order, and what
each step breaks on its way.

**Stage 1 is built** (2026-08-28). Stages 2 and 3 are specified; stage 4 is
named so the order is visible, and will be specified when it is reached.

## The mis-sizing at the centre

The worker is sized for its heaviest task and shared by its lightest.

`--concurrency=1` exists for a real reason, written down in `render.yaml`:
Celery forks one child per CPU, each child is a fully imported copy of this
application at roughly 110MB, and a URL 来源 launches Chromium beside it at
150–250MB — against 512MB on `starter`.

But a 知言 run is an `httpx.post` sitting on a socket for two to three minutes.
It uses no meaningful memory and no CPU, and it is holding the slot that exists
because of Chromium. **A memory budget is throttling a network wait.**
Everything below follows from separating the two.

---

# Stage 1 — split the queues by resource profile — **built**

| Queue | Operations | Pool | Chromium |
| --- | --- | --- | --- |
| `source-processing` | `fetch_url`, `parse_file` | prefork, `--concurrency=1`, `--max-tasks-per-child=8` | yes |
| `provider-runs` | `analyze_source`, `generate_article`, `publish_preview`, and beat's scheduled tasks | `--pool=threads --concurrency=N` | **no** |

`--pool=threads` rather than prefork is the point: prefork at concurrency 8
would be eight × 110MB. Threads give one interpreter and eight blocked sockets,
which is the shape of the work.

The existing queue name is **kept**. Renaming it strands whatever is mid-flight
on the old name across the deploy, for no benefit.

Beat's `clean_expired_data` and `recover_stalled_executions` move to
`provider-runs`. They are database and R2 work; the heavy queue's single slot is
too scarce to spend on a sweep.

## What changes

**Routing.** `execution_dispatch.py` gains the second queue name and an
operation-to-queue map, and `dispatch()` takes the operation — which every
caller already has, since it has just created the Execution row. Both names stay
in that one module and are imported by both sides, for the reason
`EXECUTION_QUEUE`'s docstring already gives: a producer that sends where no
consumer listens fails in the quietest way available.

**Services.** `liyan-worker` becomes `liyan-worker-heavy` and
`liyan-worker-provider`. The provider worker drops `uv run playwright install
chromium` from its build entirely — roughly 95MB and a minute per deploy, for a
process that never opens a page.

**The database engine.** Every worker task currently constructs its own
`Database`, and `create_engine` with no pool arguments gets SQLAlchemy's default
`QueuePool`: up to fifteen connections per engine. At `--concurrency=1` that is
one engine at a time and nobody notices. At eight threads it is eight live pools
against one small Postgres, and the failure is intermittent connection
exhaustion under load — which reads as a database problem rather than a
pool-sizing one.

One engine per worker process, shared across threads (SQLAlchemy engines are
thread-safe), with `pool_size` derived from concurrency. This must land **with**
the split, not after it. It also removes a standing waste: a fresh TCP and TLS
handshake to Postgres on every run.

**Health.** `record_heartbeat` is written on the way into each run, deliberately
— "a worker that is processing is by definition alive". With one worker handling
everything, it is rarely idle for the fifteen minutes `DEFAULT_SILENCE` allows.
After the split `source-processing` will genuinely idle, especially now that
付费用户 gating means a user who has never paid cannot enqueue heavy work at all.
A healthy idle worker would then report `silent`.

So beat fans a no-op ping to each queue on the existing five-minute sweep
interval. Every worker then touches the heartbeat table regardless of user load,
and the signal stops being a function of demand.

The rest of the multi-worker story already works: `worker_state` takes the
*worst* of all known workers rather than the freshest, and `silent_workers`
names them. Both were written for more than one worker.

## Deployment order

The producer must never route to a queue nobody consumes.

1. Deploy `liyan-worker-provider` consuming `provider-runs`. Nothing routes
   there yet; it idles.
2. Deploy the API with the new routing.

No drain is required. Work already queued on `source-processing` at cutover
includes 知言 runs, and the heavy worker still executes them correctly:
`process_execution` branches on `operation`, not on which queue delivered it.

## Choosing N

**Ship at 4, not 8.** The wall after this split is DeepSeek, not Celery, and
stage 2 is what handles it. Shipping eight before that exists converts an
invisible queueing problem into a visible provider-error problem, which is worse
— users see it, and under `ADR-0005` every such failure spends a target's retry
allowance.

Raise N once the limiter in stage 2 exists. After that the limiter is the real
bound and Celery concurrency stops mattering much.

## What this does not buy

Roughly 8× the 知言 throughput, and a URL fetch that no longer waits behind
somebody's article generation. It does **not** meaningfully change pricing:
worker seconds are about 4% of a short 知言 run's cost, so eight times cheaper
worker time moves it from 28 额度 to 27.

## Comments this made false, and what they say now

This repository keeps its reasoning in comments, so these changed with the work
rather than after it:

- `--without-gossip --without-mingle` in `render.yaml` — was "There is one."
  Both workers still set it: they never need to find each other.
- `EXECUTION_QUEUE` in `execution_dispatch.py` — was "The one queue this system
  uses." Now `SOURCE_QUEUE` and `PROVIDER_QUEUE`, with `QUEUE_BY_OPERATION`
  between them and `queue_for` defaulting an unrouted operation to the heavy
  queue, which is the conservative answer.
- `limits.md`, **"The one that everything else follows from"** — rewritten
  rather than amended: the premise was one slot and there are now five.

## Two things the specification above did not anticipate

Both were found building it, and both are the kind that fail quietly.

**A renamed worker never stops being silent.** `worker_state` takes the worst of
every heartbeat row, so `liyan-worker` — a name nothing writes any more — would
have held readiness at `silent` permanently after the deploy, naming a process
that no longer exists. `worker_health.forget_retired_workers` drops a row that
has been quiet for a week, on the cleanup sweep. Days rather than minutes so the
two readings stay unconfusable: a quarter of an hour is a fault, a week is a
decommissioning.

**The pool has to be told the concurrency.** `--concurrency` is passed to Celery
on the command line and nothing in Python can read it, so `LIYAN_WORKER_CONCURRENCY`
carries the same number to `share_engine`. They are set together, per service,
and a pool smaller than the concurrency it serves is exactly the intermittent
connection exhaustion this stage was supposed to prevent.

---

# Stage 2 — provider saturation

## First, find out what actually failed

`limits.md` records that "under a sequence of them DeepSeek began answering
`busy`". That sentence needs checking before anything is designed on it, because
`busy` is **立言阁's own word**, not DeepSeek's: ADR-0005 puts redaction at the
知言 boundary, where every failed run leaves as `busy` / 服务繁忙，请重试.

What the browser suite saw is therefore consistent with rate limiting, and
equally consistent with a timeout, a rejected report, or a 500. The real codes
are on `Execution.error_code` and `internal_error`, kept for exactly this. Read
those rows from Staging first.

## The principle

> **Waiting is invisible. Failing is not.**

A run that waits stays `running` and the user sees 处理中, which is true. A run
that fails shows 服务繁忙 *and spends the target's allowance* — one automatic
attempt, then two manual retries in a rolling thirty minutes.

That allowance exists to bound repetition the **user** asked for. Spending it on
立言阁's own concurrency decision charges the user for a choice they did not
make. So saturation must produce waiting, and must not produce failure.

## The limiter

A Redis-backed semaphore, `LIYAN_PROVIDER_MAX_CONCURRENCY`, bounding concurrent
provider calls across every worker and both operations. Acquired immediately
before the call, released after.

It is deliberately independent of Celery concurrency. Celery concurrency bounds
threads; the limiter bounds provider calls. They are different resources, and
conflating them is what forces a choice between throughput and provider errors.

## Deferral rather than failure

If no slot frees within a bounded wait, the same Execution is **re-dispatched** —
same row, same `attempt`, same `origin`, status back to `queued`. Nothing is
spent because nothing new was created, and the run stays inside
`ACTIVE_EXECUTION_STATUSES`, so the per-user capacity ceiling still counts it,
correctly: it is still holding the user's share.

A `deferrals` column on `Execution` caps the loop. Past the cap the run fails
for real as `provider_rate_limited` and picks up the sixty-second backoff that
already exists. A column rather than a Redis key, so it survives a flush and an
operator can see it.

## A global cooldown

`retry_allowed_at` is per-Execution. When the provider does refuse, every
in-flight run backs off independently and they all return together at t+60 — a
thundering herd that re-triggers the limit it was waiting out.

A shared "provider cooling until T" key, checked before acquiring a slot,
staggers them. The per-target backoff stays exactly as it is: that one is the
user-facing contract.

## The 429 asymmetry — fixed

`provider_rate_limited` is in `RECOVERABLE_FAILURE_CODES` with a sixty-second
backoff on **both** sides. Until now the detection existed on only one:
`liyan/deepseek.py` tested `status_code == 429`; `zhiyan/deepseek.py` mapped
every non-200 to `provider_unavailable`.

So the operation that actually saturates a provider — the long one, the one
that searches, the one about to run several at a time — was the only one that
could not earn its own rate-limit backoff. It took the generic thirty seconds
instead, and `provider_rate_limited` was unreachable on the 知言 side.

Nothing would ever have reported it. ADR-0005 redacts both failures to the same
服务繁忙 at the 知言 boundary, so the difference was invisible to users and
mattered only to the backoff: every 429 simply came back in half the time it
should have, and asked again.

知言 now tells them apart, and
`test_being_rate_limited_is_told_apart_from_the_provider_being_unwell` holds it
there.

## What this breaks in billing

`worker_milliseconds` is `finished_at − started_at`. A run that waits on the
limiter would have that wait metered as worker time, so **users would be charged
more precisely when the service is degraded**.

The fix is to stop metering worker seconds for LLM operations altogether. After
the split a 知言 run's worker cost is about $0.00006 — 0.4% of its total — so
folding it into the flat capture fee costs no accuracy, removes a term from the
meter, and makes the distortion impossible rather than corrected for. `credits.md`
equation ② loses its worker term; the capture fee absorbs it, which is what the
capture fee is for.

## Order

1. Read the real `error_code` values from Staging.
2. ~~知言's 429 detection.~~ Done.
3. Limiter and deferral.
4. Global cooldown.
5. Drop worker-seconds metering for LLM operations.

---

# Stage 3 — fairness under 额度

Once people pay, free work delaying paid work stops being a queueing question
and becomes a refund conversation. This stage is about who reaches the provider
first, and it is deliberately the smallest of the three.

## It belongs to the limiter, not to the queues

The obvious shape is a queue per tier with its own worker. It is the wrong one.

After stage 2 the **limiter** is the real bound, not Celery. Two queues with
eight threads each still contend for the same semaphore, so tiering them buys a
second Render service and a static split — free workers idling while the paid
queue backs up — without controlling the thing that actually decides who gets
served.

Tiering the limiter instead makes this stage an extension of stage 2 rather
than new infrastructure.

## Reserve for paid; do not cap free

The formulation is the whole design:

- **Capping free** at some share leaves provider capacity idle whenever no
  付费用户 is working, which is most of the time early on.
- **Reserving** slots for 付费用户 does not. Free work may use everything,
  including the reserved slots while they are unclaimed; paid work always finds
  one immediately, because the reservation is what it is for.

## Deferral already does the queue-jumping

Stage 2's deferral gives priority without any priority mechanism. A thread picks
up a free-tier run, asks the limiter, finds free's share taken, defers — and
takes the next task, which may be paid. No Celery priorities, which behave
inconsistently on Redis; no head-of-line blocking; no second queue.

But the two reasons a run defers are not the same thing and must not share a
cap:

| Why it deferred | Cap | How it ends |
| --- | --- | --- |
| The provider is saturated | Bounded | `provider_rate_limited` — a real failure |
| This tier is at its share | **Unbounded**, with backoff | It waits, and then it runs |

Conflating them would fail free users' work with 服务繁忙 whenever the product
is busy. Being asked to wait because you have not paid is a product decision.
Being told the service is broken is a lie about one.

## `max_active_executions_per_user` changes meaning

Its own docstring is about to be wrong:

> Raising it does not buy throughput — there is still one slot — it only lets
> one user queue more of it.

After stage 1 there are eight, so raising it **does** buy that user throughput,
at other users' expense. The number stops being purely protective and becomes an
allocation: roughly 6 for a free user and 12 for a 付费用户.

`limits.md` needs the same rewrite here as it does for its one-slot premise. The
ceiling is no longer what protects the provider — the limiter is — and the
ceiling's remaining job is to stop one user monopolising a tier's share.

## What it costs a user to wait

A deferred run holds its 预扣 for as long as it waits. That is right — the user
did commit to the work — but it means a busy period leaves a free user's 剩余额度
committed with nothing visibly happening. The 使用记录 row for a deferred run
must say 等待中 rather than showing a bare hold, or the product looks like it
has taken 额度 and stopped.

## When this is worth building

Not yet, and the honest reason is that the contention it manages does not exist.
Stage 3 matters once enough 付费用户 are working at the same time to compete,
which is a fact about the business rather than the system. Stages 1 and 2 are
worth building before anyone pays; this one is not.

---

# Stage 4 — named, not specified

**Postgres `basic-256mb`.** `executions.input_snapshot` and `stale_result` are
JSON columns on the hottest table. Large payloads belong in R2, which is already
wired, and `cleanup.py` already knows how to let go of things.

**Polling load.** Every workbench client's interval is server load, and it lands
on Postgres. ETag plus a short cache is a day's work; SSE is several. Neither is
close yet, and both are cheap to see coming.

## Bugs found while specifying this

Two were live and independent of any scaling work, so they were fixed rather
than scheduled. Both were invisible by construction, which is why each now has
a test that fails without its fix.

| | Where | What was wrong |
| --- | --- | --- |
| **Fixed** — beat's heartbeat was never written | `celery_worker` | `record_heartbeat` used `settings.worker_name`, but a scheduled task runs on the **worker**, not on beat. No `liyan-beat` row therefore existed, a dead beat hid behind the worker's own heartbeat, and cleanup and stalled recovery could both stop while `/health/ready` said `beating` — the exact failure the docstring named. Scheduled tasks now record both names, each covering the other's blind spot. |
| **Fixed** — 知言 could not detect a 429 | `zhiyan/deepseek.py` | See §The 429 asymmetry. |
| **Open** — an engine per task | `database.Database` | Not a bug at `--concurrency=1`. Becomes connection exhaustion the moment stage 1 raises it, so it is specified there rather than here. |
