# Setting up 立言阁

A runbook, in the order that keeps you unblocked. The application is built so
that a missing service disables one capability and nothing else, so the fastest
route is: get it running with nothing configured, then add one service at a
time and verify each before moving on.

If you only want it running on your machine, Part 1 and Part 2 are enough. Parts
3 and 4 are for Staging and Production.

---

## Part 0 — What you need first

**On your machine:** Python 3.13 (`.python-version`), Node 22 (`.nvmrc`),
[uv](https://docs.astral.sh/uv/), and Docker.

**Accounts.** All are free to start except DeepSeek, which is pay-as-you-go:

| Service | What it does here | Needed for |
| --- | --- | --- |
| Supabase | Email sign-in | Signing in at all |
| DeepSeek | 知言 analysis, 立言 generation | Producing reports and articles |
| Cloudflare R2 | Stores uploaded file bytes | PDF/DOCX/TXT/MD 来源 only |
| LSForum Blog | Receives a Preview | Publishing |
| Render | API, worker, beat, PostgreSQL, queue | Staging/Production |
| Vercel | The workbench | Staging/Production |
| Sentry | Client error reports | Optional, everywhere |

---

## Part 1 — Running it locally

### 1. Dependencies and infrastructure

```bash
docker compose up -d
```

That starts PostgreSQL on **5433** and Redis on 6379.

```bash
uv sync
npm install
cp .env.example .env
```

URL 来源 are extracted by driving a headless browser, and the browser is not a
Python package — `uv sync` installs crawl4ai but not the Chromium it needs:

```bash
.venv/bin/playwright install chromium
```

> **Skip it and every URL 来源 fails** with "The article could not be fetched",
> while the log says only `fetch_failed`. The real reason — Playwright naming a
> binary that does not exist — is recorded on the Execution row.

> **Why 5433, and why `127.0.0.1`.** A machine-wide PostgreSQL — Homebrew's or
> Postgres.app's — commonly holds `127.0.0.1:5432`, and it wins over Docker's
> wildcard bind. Connecting there succeeds and then fails with `role "liyan"
> does not exist`, which reads like a broken container rather than the wrong
> server. Publishing on 5433 sidesteps it. Use `127.0.0.1` rather than
> `localhost` too: `localhost` may resolve to `::1` and reach the other server
> first.

### 2. Create the schema

```bash
.venv/bin/python -m alembic upgrade head
```

### 3. Start the three processes

Each in its own terminal. All three are needed; the second and third fail
silently if you skip them.

```bash
.venv/bin/python -m uvicorn liyan_server.app:app --reload --port 8000
```

```bash
.venv/bin/celery -A liyan_server.celery_worker worker --loglevel=info
```

```bash
.venv/bin/celery -A liyan_server.celery_worker beat --loglevel=info
```

Then the workbench:

```bash
npm run dev:web
```

### 4. Verify

```bash
curl -s localhost:8000/health/ready | python3 -m json.tool
```

Expect `database: available` and `queue: available`. `object_storage:
unconfigured` and `worker: unknown` are correct at this point — you have not
configured R2, and no work has run yet.

**You now have a working application** that can create 立言任务 from pasted text
and URLs. It cannot sign anyone in, analyse anything, accept a file, or publish.
Each of those is one service below.

---

## Part 2 — The services, one at a time

### Supabase — sign-in

Nobody can sign in until this is done, so do it first.

1. Create a project at [supabase.com](https://supabase.com).
2. **Authentication → Sign In / Providers → Email**: enable it, and enable
   **Email OTP**. The workbench signs in with a six-digit code, not a password
   and not a magic link.
3. **Project Settings → API** gives you the project URL and the publishable key.

```bash
LIYAN_SUPABASE_ISSUER=https://<ref>.supabase.co/auth/v1   # note the /auth/v1
LIYAN_ALLOWED_EMAILS=you@example.com
VITE_SUPABASE_URL=https://<ref>.supabase.co               # note: no /auth/v1
VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
```

> **Three ways this bites.** The issuer *must* end in `/auth/v1` and must match
> the token's `iss` exactly, or every token is rejected. `VITE_SUPABASE_URL`
> must *not* have that suffix. And use the `sb_publishable_` key — never the
> `sb_secret_` one, which every browser would receive.

> **`LIYAN_ALLOWED_EMAILS` is a separate gate.** A valid Supabase account whose
> address is not on this list is refused. It is also separate from the `emails`
> on a publication target: an address can be allowed to sign in and still see no
> destination to publish to.

**Verify:** restart the API and the Vite dev server (Vite bakes `VITE_*` in at
boot), open the workbench, request a code, and sign in.

### DeepSeek — 知言 and 立言

1. Get a key at [platform.deepseek.com](https://platform.deepseek.com) and add
   credit.
2. `LIYAN_DEEPSEEK_API_KEY=sk-...`

Restart the **worker** — this key is read there, not by the API.

**Verify:** create a task from pasted text. 知言 should start on confirmation and
produce a report. Without the key, runs fail immediately with
`provider_unconfigured` and everything else keeps working.

### Cloudflare R2 — uploaded files

Only needed for PDF, DOCX, TXT, and Markdown 来源. Pasted text and URLs never
touch it.

1. **R2 → Create bucket.** One per environment: `liyan-local`, `liyan-staging`,
   `liyan-production`.
2. **R2 → Manage API Tokens → Create token**, scoped to that bucket, with Object
   Read & Write.
3. Copy the access key id, the secret, and the endpoint.

```bash
LIYAN_R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
LIYAN_R2_ACCESS_KEY_ID=...
LIYAN_R2_SECRET_ACCESS_KEY=...
LIYAN_R2_BUCKET=liyan-local
```

> **The endpoint must exclude the bucket name.** Cloudflare's dashboard shows an
> "S3 API" value with the bucket appended; using it verbatim produces errors
> that look like a permissions problem. Keep only
> `https://<account-id>.r2.cloudflarestorage.com`.

> **Never share a bucket between environments.** Cleanup finds abandoned uploads
> by listing the bucket and removing whatever no database row names. Pointed at
> a shared bucket, Staging's sweep would delete Production's uploads — from
> Staging's database, every one of them is an orphan.

All four settings are required together. **Verify** against the real bucket,
which is the only thing that proves the credentials, endpoint, and bucket name
agree:

```bash
LIYAN_LIVE_R2=1 .venv/bin/python -m pytest apps/server/tests/test_r2_live_contract.py
```

It writes one object, reads it back, and deletes it. The normal suite skips it.

### LSForum Blog — publishing

1. Ask LSForum for an ingest credential. It is issued as `INGEST_API_KEY`.
2. Set it as `LIYAN_BLOG_INGEST_TOKEN`.
3. Describe the destination:

```bash
LIYAN_PUBLICATION_TARGETS=[{"key":"lsforum","display_name":"LSForum Blog","site_url":"https://blog-lsforum.vercel.app","api_base_url":"https://blog-lsforum.vercel.app","emails":["you@example.com"]}]
```

> **`emails` must include an address that can sign in.** The publication target
> and `LIYAN_ALLOWED_EMAILS` are unrelated settings; a target naming only
> addresses that cannot sign in leaves publishing quietly unavailable. The
> server warns about this at startup rather than letting you discover it later.

> **A Preview is a real Blog item.** 立言阁 cannot retract one and the Blog API
> offers no way to look one up (ADR-0001). Point Staging at a Blog that does not
> matter, or leave it unconfigured — never at Production's.

Neither URL includes the `/api/v1` path; the adapter adds it.

### Sentry — client errors (optional)

Create a project (platform: React) and set `VITE_SENTRY_DSN`. Leave it blank
locally: without a DSN, Sentry never initialises and nothing is sent anywhere.

Reports are scrubbed before they leave the browser — no request bodies, no query
strings, no authorization header, no user beyond an id, and no exception
messages, since those quote whatever they were handed.

---

## Part 3 — Staging and Production on Render

`render.yaml` describes **one** environment. Staging and Production are two
separate deployments of it, with their own service names and their own secrets.
Do Staging first and completely; it is the rehearsal for Production.

### 1. Create the Blueprint

Render Dashboard → **New → Blueprint**, point it at this repository. It reads
`render.yaml` and proposes five resources: `liyan-api`, `liyan-worker`,
`liyan-beat`, `liyan-postgres`, and `liyan-queue`.

For Staging, give every service a distinguishing name (`liyan-api-staging`, and
so on) so the two environments cannot be confused in the dashboard.

### 2. Enter the secrets

Render prompts for every value marked `sync: false`, because none of them are
committed. Most live in the `liyan-shared` environment group, so you enter them
once per environment and all three processes get them:

`LIYAN_DEEPSEEK_API_KEY`, `LIYAN_R2_ENDPOINT_URL`, `LIYAN_R2_ACCESS_KEY_ID`,
`LIYAN_R2_SECRET_ACCESS_KEY`, `LIYAN_R2_BUCKET`, `LIYAN_PUBLICATION_TARGETS`,
`LIYAN_BLOG_INGEST_TOKEN`, `LIYAN_ALLOWED_EMAILS`, `LIYAN_SUPABASE_ISSUER`.

On `liyan-api` only, set `LIYAN_CORS_ORIGINS` to the Vercel URL for this
environment.

`LIYAN_DATABASE_URL` and `LIYAN_BROKER_URL` are wired automatically from the
database and queue in the blueprint. Migrations run as the API's pre-deploy
command, so there is no separate step.

> **Render hands out `postgresql://…`**, which SQLAlchemy reads as psycopg 2 —
> a driver this project does not install. The server rewrites a bare PostgreSQL
> URL to name psycopg 3, so `fromDatabase` wiring works untouched. Do not hand-
> edit the value to fix this: it is wired from the database resource, and an
> edit either gets overwritten or has to be maintained against it.

> **URL 来源 failing on Render with "Executable doesn't exist"** means the
> browser was installed during the build and then lost. Playwright defaults to
> `~/.cache`, which does not survive from a Render build into the running
> service; only the project directory does. `render.yaml` sets
> `PLAYWRIGHT_BROWSERS_PATH` inside the project for exactly this. If it is
> missing, the build succeeds and every fetch fails.
>
> **A different symptom, missing shared libraries** (`libnss3`, `libgbm`), means
> Chromium is there but its system packages are not.
> `playwright install --with-deps chromium` fixes that where `apt` is reachable;
> where it is not, switch that one service to a Docker runtime built on
> `mcr.microsoft.com/playwright/python`.

> **The worker is the service most likely to run out of memory.** Celery
> forks one child per CPU by default and each child is a fully imported copy of
> the application, so `render.yaml` pins concurrency to 1. Even then the sum is
> close: roughly 110MB for the parent, 110MB for the child, and 150–250MB for
> Chromium during a URL fetch, against 512MB on `starter`. If the worker is
> killed mid-fetch, raise **that one service** to `standard` — the API and beat
> are comfortable where they are. Do not raise concurrency to compensate; that
> is the number the memory limit is about.

### 3. What must never be shared between environments

Each is a separate **resource**, not a separate credential for the same one:

- **The database** — Staging must not be able to read a Production 立言任务.
- **The queue** — a shared broker lets one environment's worker pick up the
  other's Executions. The message carries only an id, so the worker would look
  it up in its own database and find nothing, or something worse.
- **The R2 bucket** — see the warning above. This is the sharpest one.
- **The Supabase project** — identities and the allowlist are per environment.
- **The Blog credential** — a Preview cannot be retracted.
- **The DeepSeek key** — so Staging's spend is legible and revocable alone.

### 4. Health checks and alerts

`liyan-api` already has `healthCheckPath: /health/ready`, so readiness
failures are covered. Three more to set, and one that Render cannot raise at
all:

| Watch for | Where |
| --- | --- |
| Deploy and service failures | Render → service → Settings → Notifications |
| Memory on `liyan-worker` | Render → service → Metrics → Alerts, near 80% |
| `execution_presumed_lost` in logs | Render → service → Settings → Log Streams |
| `"worker": "beating"` disappearing from `/health/ready` | An external uptime monitor — Render cannot see response bodies |

That last one is the failure most likely to go unnoticed: nothing is
processing, every task waits forever, and the API answers normally throughout.

[environments.md](environments.md#health-and-alerts) explains each, and why the
worker deliberately does not gate readiness.

> **Beat is a separate service and fails silently.** If it stops, nothing is
> ever cleaned up and no stalled run is ever recovered, while everything looks
> healthy. That is exactly why it writes a heartbeat of its own.

---

## Part 4 — The workbench on Vercel

One project per environment.

1. **New Project**, import the repository.
2. **Root Directory:** `apps/web`.
3. Framework preset **Vite**; `apps/web/vercel.json` supplies the rest,
   including the SPA rewrite that makes deep links work.
4. Environment variables:

```
VITE_API_BASE_URL=https://liyan-api-staging.onrender.com
VITE_SUPABASE_URL=https://<ref>.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_...
VITE_SENTRY_DSN=            # optional
```

5. Go back to Render and set `LIYAN_CORS_ORIGINS` on `liyan-api` to this
   project's URL. Until you do, the browser is blocked by CORS.

> `VITE_*` values are compiled into the bundle at build time. Changing one needs
> a redeploy, not a restart. And never put a secret behind a `VITE_` name —
> every visitor receives it.

---

## Part 4¼ — When something fails and the terminal is unhelpful

A failed run logs `execution_failed` with its operation, attempt, and error
code. The reason itself is deliberately not there: a provider's error text
quotes whatever it was handed, and this application hands providers 来源 bodies
and article drafts. Logs get shipped and retained; that text should not.

So the detail is pulled rather than pushed:

```bash
.venv/bin/python scripts/explain_execution.py --recent
```

or, with an id from a log line:

```bash
.venv/bin/python scripts/explain_execution.py <execution-id>
```

It prints what the user was told, and what actually happened.

---

## Part 4½ — Proving the local stack before you provision anything

Two bugs got past 347 passing tests: a database port collision and a worker
consuming a queue nothing was sent to. Neither was application logic, and
neither was visible to a suite where the queue is a double. So there is an
opt-in check that runs the real thing.

```bash
LIYAN_LIVE_STACK=1 \
LIYAN_TEST_DATABASE_URL=postgresql+psycopg://liyan:liyan@127.0.0.1:5433/liyan \
  .venv/bin/python -m pytest apps/server/tests/test_live_stack.py
```

It starts a real Celery worker against your real broker and a fresh database,
dispatches an Execution through the real API, and waits for the worker to
collect it. Nothing is mocked. It costs nothing and takes a few seconds.

Add real providers when you want the whole chain proven:

```bash
LIYAN_LIVE_PROVIDERS=1   # a real 知言 run. Spends DeepSeek credit.
```

> **`LIYAN_LIVE_BLOG=1` is deliberately separate.** A Preview is a real item on
> a real Blog, cannot be retracted, and cannot be looked up again. Point it at a
> Blog that does not matter — never at Production's.

Run this before provisioning. Everything it catches is cheaper to find here.

---

## Part 5 — Verifying an environment end to end

In order. Each step depends on the one before.

1. `curl https://<api>/health/live` → `{"status":"alive"}`
2. `curl https://<api>/health/ready` → `status: ready`, with `database` and
   `queue` both `available`
3. Open the workbench and sign in with an allowlisted address
4. Create a 立言任务 from pasted text → 知言 runs and produces a report
   (proves the worker and DeepSeek)
5. Re-check `/health/ready` → `worker` is now `beating`
6. Upload a PDF 来源 → it parses (proves R2)
7. Generate a 立言文章, save a Revision, publish it → a Preview URL comes back
   (proves the Blog credential)
8. Wait for one beat interval and check the logs for `cleanup_finished`
   (proves beat is alive)

If step 5 never leaves `unknown`, the worker is not running or cannot reach the
database. If step 8 never appears, beat is not running — and nothing else will
tell you.

---

## Appendix — Which setting breaks what

Everything degrades to one missing capability. Nothing takes the application
down.

| Blank | What stops | What still works |
| --- | --- | --- |
| `LIYAN_SUPABASE_ISSUER` | Signing in | Nothing user-facing |
| `LIYAN_DEEPSEEK_API_KEY` | 知言报告, 立言文章 | Task creation, 来源 intake |
| `LIYAN_R2_*` | File 来源 | Pasted and URL 来源, everything after |
| `LIYAN_PUBLICATION_TARGETS`, `LIYAN_BLOG_INGEST_TOKEN` | Publishing | Everything up to publication |
| `VITE_SENTRY_DSN` | Client error reports | Everything |

Each announces itself at startup and through `/health/ready`, so a gap is
visible before a user trips over it.

See [environments.md](environments.md) for the reasoning behind the isolation
rules and how the health signals are meant to be read.
