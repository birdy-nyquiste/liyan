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
