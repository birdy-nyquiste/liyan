# 立言阁浏览器插件

The browser client, published as **LiYan Studio Extension**.
`docs/design/the-browser-extension.md` says what it is and why it is shaped
this way; this file says how to run and ship it.

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

## Building for a deployed 立言阁

Do not edit `.env`. `vite build` runs in production mode, so it reads
`.env.production` from the repo root **on top of** `.env` and the mode-specific
file wins — for the bundle and for the generated manifest alike. Create it once:

```
VITE_API_BASE_URL=https://…            # the deployed API
VITE_WEB_BASE_URL=https://…            # the deployed 工作台
VITE_SUPABASE_URL=https://….supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_…
```

Then `npm run package:extension`, and your local `.env` still points at
localhost for everyday work.

It is gitignored and stays out of the repo. Nothing in it is a secret — every
value reaches every browser that installs the build — but it is the one place
that says which 立言阁 a package belongs to, and a deployment address is not
something a checkout should be able to change by being stale. So the manifest
of a finished package is the record, and `.env.production` is a local thing you
keep. The sb_secret_ key must never appear here, and must never appear behind a
`VITE_` name anywhere.

Values passed on the command line win over the file, which is how a one-off
staging package is made without keeping a second file for it:

```
VITE_API_BASE_URL=https://staging… npm run package:extension
```

`package` refuses to build when any of the three addresses is not a published
one — not https, or a host only this machine can reach, or missing. That is the
failure it exists for: without `.env.production`, `.env` answers instead, and a
localhost API beside a real Supabase project builds cleanly into a package that
installs, signs a user in, and cannot make a single request. `VITE_WEB_BASE_URL`
is checked too, and it is the reason a guard beats a habit — it appears nowhere
in the manifest, so reading the manifest cannot catch it.

To build against a local 立言阁, use `npm run build:extension`, which is held
only to Supabase existing.

Check what came out anyway — the manifest names the servers the build belongs
to:

```
cat apps/extension/dist/manifest.json
```

**Bump the version first.** The Web Store refuses a package whose version is
not higher than the one live, and the manifest takes it from
`apps/extension/package.json`.

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
cd apps/extension && npx vite --mode e2e --port 5199   # a dev server, not a build
```

Then open `http://localhost:5199/harness.html`.

Two things about that second command, both of which were wrong here before.
`vite` in serve mode rather than `npm run dev`, because `dev` is `vite build
--watch` and a build serves nothing — and because npm does not forward flags
through two nested `npm run`s, so `npm run dev:extension -- --mode e2e` reaches
vite as a bare `e2e`, which is not an error but a production build with a
stray argument. `.claude/launch.json` has the working form as
`extension-harness`.

The harness needs a 付费用户, and `scripts/e2e_server.py` grants 额度 rather
than selling any — `is_paying_user` is derived from a `purchase` entry in the
ledger, so a fresh e2e database lands on 尚未购买额度 and the basket cannot be
reached at all. Until the server seeds one, insert it by hand:

```
sqlite3 "$DB" "insert into credit_entries (id, owner_id, kind, amount, \
  stripe_reference, created_at) select hex(randomblob(16)), id, 'purchase', 500, \
  'pi_harness', datetime('now') from users"
```

The server prints `$DB` when it starts. `?url=` and `?title=` set the
page the "current tab" is showing, which is how the failure and duplicate
journeys are reached. `LIYAN_E2E_REAL_URL_FETCH=1` on the server makes captures
real rather than deterministic.

`?lang=zh` and `?lang=en` override the language, which in Chrome follows the
browser; that is how the listing screenshots are taken in English on a machine
set to anything.

The harness is never built: `vite.config.ts` names `popup.html` as the only
input. It is worth keeping — three defects were visible here and in no unit
test: a warning pill that called a 23,000-character article 正文偏薄, a failure
that spoke English, and a failed row that could not say which page it was.
