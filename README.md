# 立言阁

Under construction.

## Local setup

Copy `.env.example` to `.env` and fill in what you need. The file documents each
setting; the notes below cover only what is optional and what it costs you.

```bash
cp .env.example .env
```

### What you can leave blank

| Blank setting | What stops working | What still works |
| --- | --- | --- |
| `LIYAN_R2_*` | Uploading PDF, DOCX, TXT, or Markdown 来源 | Everything else, including pasted text and URL 来源 |
| `LIYAN_DEEPSEEK_API_KEY` | Producing 知言报告 and 立言文章 | Task creation and 来源 intake |
| `LIYAN_PUBLICATION_TARGETS`, `LIYAN_BLOG_INGEST_TOKEN` | Publishing a Revision to Blog | Everything up to publication |
| `LIYAN_STRIPE_*` | Buying 额度 | Everything else, including spending the 额度 a user already has |

Each of these announces itself at startup and through `/health/ready`, so a gap
is visible before a user trips over it rather than after.

### File 来源 need Cloudflare R2

R2 stores the original bytes of an uploaded document so the worker can parse
them. Pasted text and URL extraction never touch it: their normalized body is
written straight to PostgreSQL. That is why an unconfigured bucket stays
invisible until somebody uploads a file.

All four `LIYAN_R2_*` settings are required together. With any of them blank:

- the server logs `object_storage_unconfigured` once at startup, naming what is missing;
- `GET /health/ready` reports `checks.object_storage: "unconfigured"`, distinct
  from `"unreachable"` for a bucket that is configured but not answering;
- an upload is refused with an explanation instead of advice to retry.

Readiness reports object storage without gating on it. A deployment that cannot
accept uploads still serves everything else, and a short R2 outage must not
become a restart condition.

To configure it, create an R2 bucket and an API token scoped to that bucket in
the Cloudflare dashboard, then set the S3-compatible endpoint
(`https://<account-id>.r2.cloudflarestorage.com`), the access key id, the secret
access key, and the bucket name.

Once it is configured, an opt-in test proves the credentials, endpoint, and
bucket name actually agree — something the in-memory double cannot tell you:

```bash
LIYAN_LIVE_R2=1 .venv/bin/python -m pytest apps/server/tests/test_r2_live_contract.py
```

It writes one object to the configured bucket and deletes it again. The default
suite skips it and stays offline.

### Buying 额度 needs Stripe

Three settings, required together: `LIYAN_STRIPE_SECRET_KEY`,
`LIYAN_STRIPE_WEBHOOK_SECRET`, and `LIYAN_STRIPE_CREDIT_PACKS`. With any of
them blank the workbench says 购买功能尚未开放 rather than offering a button that
cannot work, and `/health/ready` reports `checks.billing: "unconfigured"`.

A secret key without a signing secret is the half-configuration worth naming:
Checkout would open and nothing would ever credit, so it reports as
unconfigured too.

Fulfillment happens on the webhook, never on the redirect back — a user who
closes the tab after paying has still paid. Developing against it therefore
needs Stripe's own forwarder, which prints the signing secret to use:

```bash
stripe listen --forward-to localhost:8000/webhooks/stripe
```

Once it is configured, an opt-in test proves the 额度包 in `.env` are Prices
that actually exist in that account, and that they still charge what
`docs/operations/credits.md` says an 额度包 costs:

```bash
LIYAN_LIVE_STRIPE=1 .venv/bin/python -m pytest apps/server/tests/test_stripe_live_contract.py
```

It opens a Checkout Session and pays nothing. Point it at a sandbox.

### Background work needs two processes

Every 知言 run, 立言 generation, file parse, and Blog submission happens in a
Celery worker, and the scheduled cleanup happens in Celery beat. They are
separate processes:

```bash
.venv/bin/celery -A liyan_server.celery_worker worker --loglevel=info \
  --queues=source-processing,provider-runs
```

Both queues in one process: Production splits them across two workers, and
Local has no reason to. Naming them matters — a worker left to the default takes
`source-processing` only, and 知言 runs then queue up with nobody listening.

```bash
.venv/bin/celery -A liyan_server.celery_worker beat --loglevel=info
```

Without the worker, everything a user starts stays queued. Without beat, nothing
is ever cleaned up and no stalled Execution is ever noticed: abandoned uploads
keep paying for storage, deleted 立言任务 stay on disk past their 30 days, and a
run whose worker died waits forever. None of it raises anything — the API keeps
answering — so an environment that skips beat looks healthy while its bucket
grows. `GET /health/ready` reports `worker: silent` when nothing has processed
recently, which is the signal to alert on.

## Environments

[docs/operations/setup.md](docs/operations/setup.md) is the runbook: what to
create in Supabase, DeepSeek, Cloudflare R2, LSForum, Render, and Vercel, in the
order that keeps you unblocked, with a verification step after each one.

[docs/operations/environments.md](docs/operations/environments.md) is the
reasoning behind it — what must never be shared between Local, Staging, and
Production, and how to read the health signals.

## Checks

```bash
.venv/bin/python -m pytest        # server tests
.venv/bin/python -m ruff check .  # server lint
.venv/bin/python -m mypy          # server types
npm run test:web                  # workbench tests
npm run lint:web
npm run typecheck:web
npm run api:check                 # OpenAPI and generated types must not drift
```

Everything above is deterministic and offline, which is what makes it worth
running on every change — and also what stops it from telling you that DeepSeek
answers or that a Supabase project is configured. Those checks are opt-in, and
[docs/operations/release-gate.md](docs/operations/release-gate.md) is the order
to run them in before a release, with what each one is allowed to prove.

### The browser suite

```bash
npm run test:e2e --workspace @liyan/web
```

Starts a disposable server (`scripts/e2e_server.py`: the real application, a
throwaway database, identity and the paid providers substituted) and a Vite dev
server, then drives the whole workflow through Chromium. Point it at a real
deployment instead with `LIYAN_E2E_BASE_URL`, `LIYAN_E2E_EMAIL`, and
`LIYAN_E2E_OTP`; the release gate document explains why that run is the one that
counts.

The browsers are a separate install, once:

```bash
npx playwright install chromium --workspace @liyan/web
```

### Limits and accessibility

[docs/operations/limits.md](docs/operations/limits.md) states what bounds one
user's share of the single worker slot, and how to measure it with
`scripts/load_check.py`.
[docs/operations/accessibility.md](docs/operations/accessibility.md) states the
eight thresholds a release is gated on, and which two are still checked by hand.
