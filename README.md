# 立言阁

The Phase 1 workspace is a React/Vite workbench backed by a FastAPI modular monolith. FastAPI's OpenAPI document is the front/back contract; the browser uses generated TypeScript types with `openapi-fetch`.

## Run locally

Prerequisites: Docker, Python 3.13 with `uv`, and Node.js 22 with npm.

1. Install dependencies and copy local configuration:

   ```sh
   uv sync
   npm install
   cp .env.example .env
   CRAWL4_AI_BASE_DIRECTORY=/tmp/liyan-crawl4ai uv run crawl4ai-setup
   ```

   Configure `.env` with a Supabase project that uses asymmetric JWT signing keys and an Email OTP template containing `{{ .Token }}`, plus a Cloudflare R2 bucket and S3-compatible endpoint credentials. Set `LIYAN_ALLOWED_EMAILS` and all R2 values only on the server; they are deliberately not `VITE_` values and are never sent to the browser. The Supabase publishable key is safe for browser use. File byte, page, normalized-text, timeout, and DOCX archive limits are configurable through the corresponding `LIYAN_FILE_*` values.

   知言 needs `LIYAN_DEEPSEEK_API_KEY`. Without it a run fails immediately with `provider_unconfigured` and no report is produced; everything else in the workbench still works. `LIYAN_ZHIYAN_MODEL` defaults to the confirmed `deepseek-v4-flash`, and `LIYAN_DEEPSEEK_BASE_URL` and `LIYAN_ZHIYAN_TIMEOUT_SECONDS` have working defaults. The deterministic test suite never calls DeepSeek, so no key is needed to run the checks below.

2. Start PostgreSQL and Redis, then apply all migrations:

   ```sh
   docker compose up -d database broker
   uv run alembic upgrade head
   ```

3. Start the server:

   ```sh
   uv run uvicorn liyan_server.app:app --app-dir apps/server/src --reload
   ```

4. In another terminal, start the workbench:

   ```sh
   npm run dev:web
   ```

5. In another terminal, start the source-processing worker:

   ```sh
   uv run celery -A liyan_server.celery_worker:celery_app worker -Q source-processing --loglevel=INFO
   ```

Open [http://localhost:5173](http://localhost:5173). The status badge should show `服务正常`. An allowlisted user can request and verify an Email OTP, then prepare pasted text, a public article URL, or an uploaded PDF, DOCX, TXT, or Markdown document before confirming a numbered `立言任务`. URL extraction runs through Crawl4AI; file parsing is deterministic and uses no LLM or OCR. Confirming a task queues one 知言 run per source immediately after the creation transaction commits, and the sources progress in parallel. Opening a task shows one 知言 area per source Revision of its current version alongside the 立言 area, which stays shut until every current report has succeeded. A failed run reads as 服务繁忙，请重试; the initial operation recovers once by itself, after which each manual retry creates exactly one run, at most twice per rolling 30 minutes, with the countdown and remaining allowance decided by the server. Terminating a run discards its result even if the provider answers later. 来源 editing stages additions, replacements, direct edits, and logical deletions without changing the current version; one save creates a new immutable 任务版本, reuses unchanged successful analysis, and queues only changed Revisions. The version selector exposes the current snapshot plus three read-only historical snapshots, and restore only moves the current-version reference. In the 立言 area, only an explicit save records an immutable 文章 Revision: generating, editing, and reloading a completed run leave history untouched. A save carries its base Revision, so a stale base is rejected while the browser-local draft stays intact, and the area lists the current Revision plus three historical ones. Restoring one appends a new current Revision with its provenance. The server marks the newest saved Revision publishable only while the browser reports no unsaved edits. The server exposes liveness at [http://localhost:8000/health/live](http://localhost:8000/health/live) and dependency readiness at [http://localhost:8000/health/ready](http://localhost:8000/health/ready).

## Verify changes

```sh
uv run ruff check apps/server scripts
uv run mypy
uv run pytest
npm run lint:web
npm run typecheck:web
npm run test:web
npm run build --workspace @liyan/web
npm run api:check
```

When the FastAPI contract changes, regenerate and commit both contract artifacts:

```sh
npm run api:generate
```
