# Local, Staging, Production

Three environments that share nothing but a schema. The point of the isolation
is not tidiness: 立言阁 spends money at DeepSeek, writes to a bucket, and creates
real items on a real Blog. Anything shared between environments turns a Staging
experiment into a Production event.

## What runs where

| Piece | Where | Notes |
| --- | --- | --- |
| Workbench | Vercel | `apps/web/vercel.json`; one project per environment |
| Server API | Render web service | Health check `/health/ready` |
| Celery worker | Render worker | Every 知言 run, 立言 generation, parse, and Blog submission |
| Celery beat | Render worker | Cleanup and the stalled-Execution sweep |
| PostgreSQL | Render | One database per environment |
| Queue | Render Key Value | Carries Execution identity only |

`render.yaml` describes one environment. Staging and Production are two separate
deployments of it with their own service names and their own secrets — never one
stack addressed by two URLs.

**A deviation worth naming:** scheduled work runs as Celery beat in a second
`type: worker`, not as a Render `type: cronjob`. The schedule then lives beside
the tasks it triggers, so the two cannot drift apart, and a missed tick is
simply a later sweep rather than a separate job with its own failure story. The
cost is that beat has no Render health check of its own — which is why it writes
a heartbeat like any other worker (below).

## What must never be shared

Each of these is a separate resource per environment, not a separate credential
for the same resource:

- **The database.** Staging must not be able to read a Production 立言任务.
- **The queue.** A shared broker would let one environment's worker pick up the
  other's Executions, and the message carries only an id — the worker would look
  it up in *its own* database and find nothing, or worse, something.
- **The R2 bucket.** Cleanup lists the bucket to find objects no row names
  (`cleanup.py`). Pointed at a shared bucket, Staging's sweep would collect
  Production's uploads: every one of them is an orphan as far as Staging's
  database is concerned. This is the sharpest reason on this page.
- **The Supabase project.** Auth identities and the allowlist are per
  environment.
- **The Blog ingest credential.** `LIYAN_BLOG_INGEST_TOKEN` and
  `LIYAN_PUBLICATION_TARGETS`. A Preview is a real Blog item; ADR-0001 means
  立言阁 cannot retract one, and v0.11 offers no lookup to find it again. Staging
  points at a Blog that does not matter, or at nothing at all.
- **The DeepSeek key.** Separate keys keep Staging's spend legible, and let one
  be revoked without stopping the product.

Every one of these is `sync: false` in `render.yaml`, so no value is committed
and Render asks per environment.

## Secrets stay on the server

The browser bundle carries only what is public by construction: the API base
URL, the Supabase project URL, and the publishable key. The Blog credential, the
DeepSeek key, and the R2 keys are read by the server and never appear in a
response — a 发布目标 is returned without its token, and a log line cannot carry
one (`observability.py` allowlists fields, so an unrecognised one is dropped).

## Health and alerts

- `/health/live` — the process is up. Liveness only.
- `/health/ready` — `database` and `queue` gate the verdict, because nothing the
  server does for a user works without them. `worker` and `object_storage` are
  reported without gating: a silent worker is a real problem that restarting the
  API does not fix, and the Technical Spec forbids making a short R2 outage a
  restart condition.

Point Render's health check at `/health/ready`. What to watch for, and how —
the split matters, because Render can raise three of these four itself and the
fourth needs something outside it.

### Render raises these

**Deploy and service failures.** Dashboard → the service → **Settings →
Notifications**, or account-wide under **Settings → Notifications**. Covers
builds that fail and services that crash-loop.

**Readiness failing.** Already wired: `liyan-api` declares
`healthCheckPath: /health/ready`, so a deployment that cannot serve is restarted
and reported through the notifications above. `database` and `queue` are what
gate that verdict.

**Memory and CPU.** Dashboard → the service → **Metrics → Alerts**. Set this on
`liyan-worker` above all: it is the service with a real ceiling, at roughly
110MB for the parent, 110MB for the child, and 150–250MB for Chromium during a
URL fetch, against 512MB on `starter`. Alert near 80% so the warning arrives
before Render kills it.

### Render cannot raise these

`checks.worker` and `checks.object_storage` are in the **body** of a response
that still returns 200. That is deliberate — a dead worker must not take the API
out of rotation, and the Technical Spec forbids making a short R2 outage a
restart condition — but it does mean Render's health check cannot see either.

**`checks.worker` = `silent`** is the failure most likely to go unnoticed:
nothing is processing, every task waits forever, and the API answers normally
throughout. The verdict is the *worst* of the known workers rather than the
freshest, because the worker and beat fail independently, and beat dying quietly
means nothing is ever cleaned up or recovered again.
`worker_health.silent_workers()` names which one.

**`checks.object_storage` = `unconfigured`** means file 来源 cannot be accepted,
permanently, until somebody edits configuration.

Reach them with an external uptime monitor that can assert on the response body
— Better Stack, Checkly, and UptimeRobot all do this on their free tiers. Point
it at `/health/ready` and alert when the body **stops** containing:

```
"worker": "beating"
```

Matching on the healthy string rather than the unhealthy one is the safer way
round: it also fires if the endpoint starts returning something unexpected,
where a search for `"silent"` would quietly pass.

**`execution_presumed_lost` and `worker_never_started` log lines** — a worker
died mid-run, or work was queued that nobody ever collected. A few of the first
are normal around a deploy; a stream is not, and any of the second means a
worker or a queue name is wrong. Reach these by sending Render's logs to a
service that alerts on content: Dashboard → the service → **Settings → Log
Streams**.

> If body-matching monitors ever feel like too much machinery, the alternative
> is an endpoint that returns non-200 when a worker has gone silent, so the
> simplest possible uptime check catches it. That has not been built, because it
> means deciding that a silent worker makes the *API* unhealthy, and it does
> not.

Client errors go to Sentry when `VITE_SENTRY_DSN` is set, scrubbed by
`apps/web/src/monitoring.ts`: no request bodies, no query strings, no
authorization header, no user beyond an id. Without a DSN, nothing is sent —
which is what Local should be.

## Still to do by hand

Provisioning is not code. Someone with the accounts has to:

1. Create the Render Blueprint from `render.yaml`, once per environment, and
   enter each `sync: false` secret.
2. Create one Vercel project per environment, with `VITE_API_BASE_URL`,
   `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, and optionally
   `VITE_SENTRY_DSN`.
3. Create a separate R2 bucket per environment. The S3 endpoint must **exclude**
   the bucket name — the Cloudflare dashboard's "S3 API" field includes it.
4. Create a separate Supabase project per environment.
5. Configure the alerts above — the three in Render's dashboard, and one
   external monitor for `"worker": "beating"`, which Render cannot see.

Until step 1 is done for Staging, there is no Staging.
