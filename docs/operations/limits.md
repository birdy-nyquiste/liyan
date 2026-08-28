# Launch limits

Every number here bounds something that would otherwise be unbounded, and each
one is written down because the failure it prevents is quiet. Nothing on this
page raises an alert when it is wrong: the queue simply grows, or a user waits,
or an instance is killed and restarted while the API keeps answering.

## The two things everything else follows from

**One Chromium slot, and four sockets.** Slow work is split across two workers
by what it costs a machine rather than by what it means (`scaling.md` stage 1).

`liyan-worker-heavy` runs `--concurrency=1` and holds the browser. Celery
otherwise forks one child per CPU, each child is a fully imported copy of this
application at roughly 110MB, and a URL 来源 launches Chromium beside it at
150–250MB — several hundred megabytes before a single 来源 is read, against
512MB on `starter`. So capture still does **one thing at a time**: one URL
fetch, or one file parse.

`liyan-worker-provider` runs `--pool=threads --concurrency=4` and holds no
browser. A 知言 run, a 立言 generation, and a Blog submission are each an
`httpx.post` waiting on somebody else's server: no meaningful memory, no CPU,
and four of them are four blocked sockets in one interpreter. So provider work
does **four things at a time**.

That split is the point. Before it, a 知言 run spent two to three minutes
holding the single slot that exists because of Chromium — a memory budget
throttling a network wait. The limits below still exist, but what most of them
now protect is one of two different resources, and the table says which.

| Limit | Setting | Default | What it protects |
| --- | --- | --- | --- |
| Executions in flight per user | `LIYAN_MAX_ACTIVE_EXECUTIONS_PER_USER` | 6 | Both workers, from one user |
| 来源 per 任务版本 | — (structural) | 3 | The size of one 知言 batch |
| Upload size | `LIYAN_FILE_MAX_BYTES` | 10MB | Memory during parse |
| Pages per PDF | `LIYAN_FILE_MAX_PAGES` | 100 | Parse time |
| Normalized characters | `LIYAN_FILE_MAX_NORMALIZED_CHARACTERS` | 500,000 | Prompt size and database rows |
| DOCX entries / uncompressed bytes | `LIYAN_FILE_MAX_DOCX_*` | 2,000 / 50MB | Zip bombs |
| URL fetch | `LIYAN_URL_FETCH_TIMEOUT_SECONDS` | 60 | Chromium holding the capture slot |
| 知言 / 立言 provider call | `LIYAN_ZHIYAN_TIMEOUT_SECONDS`, `LIYAN_LIYAN_TIMEOUT_SECONDS` | 300 | A provider thread, from a provider that stopped answering |
| Blog submission | `LIYAN_BLOG_TIMEOUT_SECONDS` | 60 | A provider thread |
| Presumed-lost run | `LIYAN_STALLED_EXECUTION_TIMEOUT_MINUTES` | 30 | Work waiting on a dead worker |

## Executions in flight per user

Every other bound in this system is per target: one active 知言 run per source
Revision (a partial unique index, not a check-then-act), one active parse per
来源. None of them stops one user from opening five 立言任务 and putting fifteen
runs in front of everybody else's first request. Nothing fails when that
happens — every 来源 says 处理中, correctly, for as long as it takes.

`execution_limits.py` is the ceiling that stops it, and it asks one question
before accepting new work: is this user already holding `MAX_ACTIVE_EXECUTIONS`
Executions in a queued, running, or cancel-requested state? If so, the request
is refused with 429 and a reason the user can act on.

Two properties are deliberate:

- **A batch admitted under the line is admitted whole.** Confirming a 任务创建
  会话 with three 来源 queues three 知言 runs from one act. Refusing the second and
  third would leave a 任务版本 half analyzed for a reason the user never chose.
  The real bound is therefore the ceiling plus one batch: **6 + 3 = 9** at the
  default.
- **Idempotent replays are never refused.** The runs a confirmation queued are
  exactly what put its user at the ceiling, so a client retrying after a dropped
  response must not be told it is too busy to repeat what it already did.

Two acts are outside the ceiling on purpose: saving a 来源编辑会话 and restoring
a 任务版本. Both queue 知言 runs, but refusing either discards editing work the
user has already done, rather than delaying work they are asking to start.

`0` disables the ceiling. That is right for Local, where one developer is not
competing with anybody, and wrong everywhere else.

### Choosing the number

6 is the smallest ceiling that leaves a normal workflow untouched: a 任务版本
holds up to three 来源, so intake can hold three Executions and the 知言 batch
that follows holds three more. Below 6 an ordinary user meets the ceiling doing
nothing unusual, which trains them to ignore it.

Raising it does not buy throughput — the workers are still one capture slot and
four provider threads — it only lets one user queue more of it. If throughput is
what is short, the answer differs by which worker is short of it: capture wants
a larger plan before more concurrency, because its ceiling is Chromium's memory;
provider work wants `--concurrency` and `LIYAN_WORKER_CONCURRENCY` raised
together, up to the point where DeepSeek rather than Celery is the wall. That
point is what `scaling.md` stage 2 is about, and it is not built.

## Measuring it

`scripts/load_check.py` drives N concurrent writers through the whole intake and
知言 path against a running stack, and prints how long a 知言报告 took at the
median and at the worst, how many never finished, and how many requests the
ceiling refused.

```bash
.venv/bin/python scripts/load_check.py \
    --base-url https://liyan-api-staging.onrender.com \
    --token "$WRITER_ONE_TOKEN" --token "$WRITER_TWO_TOKEN" \
    --sources 3 --timeout 600
```

One token is one writer, because the ceiling is per user. It writes real data
through the real API, so it is pointed at Staging or Local and never at
Production.

Run it before a release and record the answer here:

| Date | Environment | Writers × 来源 | Median 知言 | Slowest | Unfinished | Refused |
| --- | --- | --- | --- | --- | --- | --- |
| _not yet run_ | | | | | | |

**This table is empty, and until it has a row the ceiling above is reasoned
rather than measured.**

One number is known without it, from the browser suite's own runs against
Staging on 2026-08-24: **a single 知言 run takes two to three minutes**, and
under a sequence of them DeepSeek began answering `busy`. One writer alone can
therefore hold the only worker slot for minutes at a time, and the provider
refuses before the queue does — which is an argument for the ceiling existing,
and a reason to measure it with more than one writer before launch. The reasoning is sound — the memory arithmetic is real
and the batch size is structural — but a launch decision wants the second
column too. Fill it from a Staging run with the writers a launch expects.

What to read out of it:

- **Slowest ≫ median** with nothing refused means the queue is absorbing the
  load and users are waiting. Lower the ceiling or raise the plan.
- **Refusals with a low median** is the ceiling working: people are told to wait
  instead of waiting invisibly.
- **Unfinished > 0** is not a load result. It usually means the worker is not
  running at all, which `/health/ready` reports as `worker: silent`.

## Polling

The workbench polls rather than subscribes, so the client's intervals are load
too. They live in `apps/web/src/components/pollIntervals.ts`, in one place with
what each one costs; `docs/operations/environments.md` covers the health signals
that tell you when the polling is not the problem.
