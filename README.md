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

Open [http://localhost:5173](http://localhost:5173). The status badge should show `服务正常`. An allowlisted user can request and verify an Email OTP, then prepare pasted text, a public article URL, or an uploaded PDF, DOCX, TXT, or Markdown document before confirming a numbered `立言任务`. URL extraction runs through Crawl4AI; file parsing is deterministic and uses no LLM or OCR. The server exposes liveness at [http://localhost:8000/health/live](http://localhost:8000/health/live) and dependency readiness at [http://localhost:8000/health/ready](http://localhost:8000/health/ready).

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
