# 立言阁

The Phase 1 workspace is a React/Vite workbench backed by a FastAPI modular monolith. FastAPI's OpenAPI document is the front/back contract; the browser uses generated TypeScript types with `openapi-fetch`.

## Run locally

Prerequisites: Docker, Python 3.13 with `uv`, and Node.js 22 with npm.

1. Install dependencies and copy local configuration:

   ```sh
   uv sync
   npm install
   cp .env.example .env
   ```

2. Start PostgreSQL and apply all migrations:

   ```sh
   docker compose up -d database
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

Open [http://localhost:5173](http://localhost:5173). The status badge should show `服务正常`. The server exposes liveness at [http://localhost:8000/health/live](http://localhost:8000/health/live) and dependency readiness at [http://localhost:8000/health/ready](http://localhost:8000/health/ready).

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
