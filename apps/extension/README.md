# 立言阁浏览器插件

The browser client. `docs/design/the-browser-extension.md` says what it is and
why it is shaped this way; this file says how to run and ship it.

## Running it

```
npm run build:extension
```

Then in Chrome: **chrome://extensions** → enable **开发者模式** → **加载已解压的扩展程序**
→ pick `apps/extension/dist`.

Chrome loads a directory, so the build output *is* the extension. `npm run
dev:extension` rebuilds on change; press the reload arrow on the extension card
to pick it up. There is no HMR — a popup is destroyed every time it closes, so
reopening it is already most of a reload.

## Which 立言阁 it talks to

Two of the manifest's fields are the addresses of 立言阁 itself, so the manifest
is generated at build time from the same root `.env` the workbench reads:

| Value | Used for |
| --- | --- |
| `VITE_API_BASE_URL` | The API, and a `host_permissions` entry for it |
| `VITE_SUPABASE_URL` | Sign-in, and a `host_permissions` entry for it |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | Sign-in |
| `VITE_WEB_BASE_URL` | Where 购买额度 and 打开任务 send the user |

A build therefore belongs to one environment. To make a staging build, point
those at staging and build; there is no runtime switch, deliberately — an
extension that could be pointed at production by a menu is one that will be.

The build fails rather than warns when `VITE_SUPABASE_URL` is missing, because
the alternative is an extension that installs and then cannot sign anybody in.

## Why it does not need the server's CORS list

The API keeps an origin allowlist, and an extension's origin is its id — which
differs between an unpacked build and a published one, and does not exist until
publication. The manifest asks for the two hosts by name instead, which is what
lets one build work in every environment without the server being told who is
calling. `LIYAN_CORS_ORIGINS` needs no extension entry.

## Packaging for the Web Store

```
npm run package:extension
```

`apps/extension/liyan-extension.zip` is the upload. Before submitting, the
listing needs saying plainly what the permissions are for, because it is the
part reviewers ask about:

- **activeTab** — the address of the tab the user clicked from, and nothing
  else. There is no content script; the page's contents are never read.
- **storage** — the signed-in session, and the id of the 任务创建会话 being
  filled, so that closing the popup does not lose either.
- **Two host permissions** — 立言阁's own API and Supabase project. No other
  host is reachable.

The single sentence worth leading with: the extension sends 立言阁 the address
of the page, and 立言阁 fetches it. Nothing is read from the page itself.

## Running the panel without Chrome

An extension cannot be loaded into a headless browser, so `harness.html`
renders the real panel against a real server with the two things Chrome would
otherwise provide stubbed: `chrome.*`, and a signed-in session.

```
.venv/bin/python scripts/e2e_server.py --port 8099     # any bearer token signs in
npm run dev:extension -- --mode e2e --port 5199
```

Then open `http://localhost:5199/harness.html`. `?url=` and `?title=` set the
page the "current tab" is showing, which is how the failure and duplicate
journeys are reached. `LIYAN_E2E_REAL_URL_FETCH=1` on the server makes captures
real rather than deterministic.

The harness is never built: `vite.config.ts` names `popup.html` as the only
input. It is worth keeping — three defects were visible here and in no unit
test: a warning pill that called a 23,000-character article 正文偏薄, a failure
that spoke English, and a failed row that could not say which page it was.
