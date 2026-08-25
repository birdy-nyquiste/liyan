# The Phase 1 release gate

What has to be true before 立言阁 is used for real work, and what each check is
allowed to prove.

The distinction matters more than the list. Most of this suite is deterministic
and offline, which is what makes it worth running on every change — and also
what makes it unable to tell you that DeepSeek answers, that a Supabase project
is configured, or that a Blog accepts a Preview. Those are the checks that cost
something to run, and they are the ones a release actually turns on.

## The gate, in order

Run it in this order. Each step is cheap enough to be worth doing before the
next one, and a failure early means the later ones would have told you nothing.

### 1. The deterministic suite — every change

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m mypy
npm run test:web
npm run lint:web
npm run typecheck:web
npm run api:check
```

`api:check` is not a formality: `openapi.json` is committed and the workbench's
client types are generated from it, so a route whose shape changed without it
is a workbench that compiles against a server that no longer exists.

Inside the Python suite, `apps/server/tests/test_release_gate.py` is the part
that is about the *whole* workflow rather than one rule of it — pasted 来源 to
Preview URL, with ownership, idempotency, concurrency, retry, cancellation,
history, deletion, and all three publication outcomes walked end to end. Every
other file proves one thing well; that one proves they agree with each other.

### 2. The same suite against PostgreSQL — before a release

```bash
docker compose up -d
LIYAN_TEST_DATABASE_URL=postgresql+psycopg://liyan:liyan@127.0.0.1:5433/liyan \
    .venv/bin/python -m pytest
```

SQLite does not enforce foreign keys unless asked and this project never asks,
so a delete that violates a constraint passes locally and fails in production.
This is the only check that sees the difference.

### 3. The live stack — before a release

```bash
LIYAN_LIVE_STACK=1 \
LIYAN_TEST_DATABASE_URL=postgresql+psycopg://liyan:liyan@127.0.0.1:5433/liyan \
    .venv/bin/python -m pytest apps/server/tests/test_live_stack.py
```

A real Celery worker against a real broker. It exists because of a bug no
deterministic test could see: the API dispatched to one queue while the worker
consumed another, and nothing failed — the API answered 202 and every 来源 sat
at 处理中 forever.

### 4. The adapter contracts — when the provider or its configuration changes

Each is opt-in, and each proves the one thing its deterministic twin cannot:
that the thing on the other end is really shaped the way the adapter believes.

| Check | Gate | What only it can tell you |
| --- | --- | --- |
| `test_supabase_live_contract.py` | `LIYAN_LIVE_SUPABASE=1` | This Supabase project publishes JWKS keys at all — a project still on shared-secret JWTs has none, and every sign-in fails |
| `test_crawl4ai_live_contract.py` | `LIYAN_LIVE_CRAWL4AI=1` | A browser is installed and can actually extract a page |
| `test_r2_live_contract.py` | `LIYAN_LIVE_R2=1` | The credentials, endpoint, and bucket name agree with each other |
| `test_zhiyan_live_contract.py` | none — replays a captured response | The adapter still reads what DeepSeek really sent, offline |
| `test_live_stack.py` | `LIYAN_LIVE_PROVIDERS=1` | DeepSeek answers, and its answer passes acceptance |
| `test_blog_live_contract.py` | `LIYAN_LIVE_BLOG=1` | The ingest credential works, and Blog still answers with the `previewPath` the adapter requires |

`LIYAN_LIVE_BLOG` deserves its own decision every time, and it has a file of its
own so that no other check can turn it on by including it. A Preview is a real
item on a real Blog, 立言阁 cannot retract one, and v0.11 offers no way to look
one up again (ADR-0001). Every run leaves a draft behind, titled
`立言阁发布通道校验` and dated so whoever finds it knows it can be deleted. Point
it at a Blog that does not matter, and never at Production's.

A real 知言 run takes two to three minutes end to end, which is why the browser
suite waits on provider-paced work for as long as the server itself does
(`LIYAN_ZHIYAN_TIMEOUT_SECONDS`, 300s) rather than for something that felt
generous.

### 5. The browser suite — against Staging, before a release

```bash
LIYAN_E2E_BASE_URL=https://liyan-staging.vercel.app \
LIYAN_E2E_EMAIL=writer@example.com \
LIYAN_E2E_OTP=123456 \
    npm run test:e2e --workspace @liyan/web
```

Sign-in through Supabase, a 立言任务 from a pasted 来源, 知言 outcomes, article
generation and editing and saving, history restoration, deletion, and a Preview
— through a real browser against a real deployment.

The OTP is not read from a mailbox. Configure a Supabase test address with a
fixed code (Authentication → Sign In / Providers → Email → test OTPs) and use
that; a suite that needs a human to read an email is a suite that does not run.

The same specs run locally with no Staging at all:

```bash
npm run test:e2e --workspace @liyan/web
```

That run starts `scripts/e2e_server.py` — the real application on a disposable
database, with identity and the paid providers substituted — and a Vite dev
server configured from `.env.e2e`. It proves the workbench: that the buttons
exist, that they are enabled at the right moments, that the answers arrive on
screen. It cannot prove anything about a deployment, which is why step 5 is the
one the gate requires and this one is what keeps the specs honest in between.

Two specs are skipped locally and say so: OTP sign-in needs a Supabase project,
and a failing URL 来源 needs the worker's Chromium. One is skipped against
Staging: 结果未知 cannot be asked for from a real Blog.

### 6. Load and limits — before a release, and after any change to concurrency

```bash
.venv/bin/python scripts/load_check.py --base-url https://… --token … --token …
```

[limits.md](limits.md) holds the ceilings, what each protects, and the table to
record the answer in. **That table is currently empty**, which means the launch
ceiling is reasoned rather than measured. It should have a row before Phase 1 is
called done.

### 7. Accessibility — before a release

[accessibility.md](accessibility.md) states eight thresholds. Six are enforced
by tests that run in steps 1 and 5. Two — that every state change a user waits
on is announced, and that contrast meets AA — are checked by hand, and the
procedure for each is on that page.

## Where this gate stands today

The machinery is built and green. Three of the criteria it exists to serve are
not yet *met*, and none of them can be met from a developer's machine:

1. **The browser suite's OTP sign-in is not covered against Staging.** Every
   other spec has passed against the deployment (2026-08-24), including a real
   Preview created through the workbench. Sign-in itself is bootstrapped through
   Supabase's API rather than the workbench's form, because reaching the 验证码
   field means submitting the address, and that makes Supabase issue a new code
   — invalidating the one being typed. Configure a test address with a fixed
   code and set `LIYAN_E2E_FIXED_OTP=1`; the form spec then runs as written.
   Note also that no single execution covers every journey: a failing URL 来源
   is skipped locally, and 结果未知 is skipped against Staging, because a real
   Blog cannot be asked for an ambiguous answer.
2. **The launch ceiling is reasoned, not measured** (step 6). The table in
   [limits.md](limits.md) has no rows.
3. **Two accessibility thresholds have no recorded result** (step 7) — the
   announcement check and the contrast check are by hand, and nothing here
   records that they were done.

Each is a step somebody has to take once Staging exists, not a gap in the code.

## What this gate does not cover

Named rather than left to be discovered:

- **That Staging cannot reach Production's Blog credential.** The isolation is
  documented in [environments.md](environments.md) and nothing enforces or
  proves it. Configuration is entered per environment in Render, by hand, and
  the gate takes it on trust. This is the largest open hole in the gate.
- **Recovery from a partly-applied migration.** `preDeployCommand` stops a
  deploy on failure; nothing rehearses what is done next.
- **Sustained load over hours.** `load_check.py` measures a burst.
- **Anything about Production data.** No check here reads or writes it, and none
  should be made to.
