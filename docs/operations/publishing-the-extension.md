# Publishing 立言阁浏览器插件

How a package gets from this repository into the Chrome Web Store, in the order
it has to happen. `apps/extension/README.md` says how to build and run the
extension; this says how to release it.

Two decisions are already made and everything below assumes them:
**Unlisted** distribution, because the extension's 来源 collection needs a paid
立言阁 account and a public listing would mostly reach people who have none; and
**zh-CN only**, so there is no `_locales` and one listing to fill in.

---

## 0. Once, before the first release

**A Chrome Web Store developer account.** Register at
[the developer dashboard](https://chrome.google.com/webstore/devconsole) with
the Google account that should own the item — this is not easily moved later, so
it should be a company account rather than a personal one.

- **US$5**, one time, non-refundable.
- **Two-step verification is mandatory** on that account. Turn it on before you
  start; the dashboard will not let you publish without it.
- New publishers are capped at **two published items**. One extension is fine.

**A verified contact email**, set on the account. Unverified means no
publishing.

**The trader declaration.** The dashboard asks, once, whether the account is a
**trader** or a **non-trader**, and it asks before anything can be published.
This is the EU's definition, not Google's: a trader is a person or company
"acting for purposes relating to his trade, business, craft or profession", and
a non-trader is one acting outside it.

**Nyquiste Corporation is a trader.** It is a company publishing its own product
and it sells 额度. Non-trader is for someone releasing something outside their
profession. The declaration is a self-declaration and the Web Store puts the
responsibility for its accuracy on the developer, so this is not a place to
optimise.

Declaring trader means providing, and passing verification on:

- the legal name
- a physical address
- an **SMS-capable phone number** — verification is a code sent to it, so it has
  to be a number someone can actually receive on
- a contact email

**All four are published at the foot of the extension's listing page.** That is
worth knowing before choosing what the site's own legal pages disclose: it makes
"the address is on the store page but not in the 隐私政策" the state of things,
which is the wrong way round for most jurisdictions. A D-U-N-S number may be
required later for corporate phone verification; today it is not.

The declaration is account-wide rather than per-item, so neither Unlisted
distribution nor a users-in-China-only audience changes what it should say.

**A privacy policy that is live.** `https://<工作台>/privacy` — written, not a
placeholder. The Limited Use statement has to be on that page, not only in the
dashboard; it is already in `apps/web/src/public/legal.tsx`. Fill in the
`[待填]` placeholders (生效日期, 退款, 责任限制, 适用法律) and deploy before
submitting, because the reviewer will open the URL.

---

## 1. Prove the build

The extension's checks are part of the release gate — see
`docs/operations/release-gate.md`. At minimum:

```bash
npm run test:extension && npm run lint:extension && npm run typecheck:extension
```

Then walk the panel in a real browser. There is no automated browser coverage of
the extension, so this is the only thing that sees it render:

```bash
.venv/bin/python scripts/e2e_server.py --port 8099
cd apps/extension && npx vite --mode e2e --port 5199
```

`apps/extension/README.md` explains the 付费用户 the harness needs and how to
seed one. Walk at least: 未登录 → 验证码 → 主屏 → 添加三条 → 确认创建, plus a
removal and a failed capture.

---

## 2. Bump the version

The Web Store refuses a package whose version is not higher than the one live,
and it refuses it *after* the upload, which wastes a round trip.

```bash
# apps/extension/package.json — the manifest takes its version from here
"version": "1.0.1"
```

Chrome's format is one to four dot-separated integers, each 0–65535, no leading
zeros. Bump before packaging, not after.

---

## 3. Build the package

```bash
npm run package:extension
```

This reads `.env.production` from the repository root — gitignored, created once
per machine as `apps/extension/README.md` describes. It **refuses to build**
unless all three addresses are published ones: https, and not a host only your
machine can reach. That guard is the reason a missing `.env.production` can no
longer produce an uploadable package pointed at `localhost`.

Check what came out anyway. The manifest names the servers the package belongs
to, and it is the record of which 立言阁 this build is for:

```bash
cat apps/extension/dist/manifest.json
```

The upload is `apps/extension/liyan-extension.zip`.

---

## 4. The listing assets

The images themselves are not in the repository — they are listing material,
not product, and they change without the code changing. Keep them wherever the
marketing material lives. The scripts that make them are in `scripts/`.

| Asset | Size | Required | Notes |
| --- | --- | --- | --- |
| Store icon | 128×128 PNG | yes | 96×96 of artwork with 16px transparent padding. `apps/extension/public/icons/icon-128.png` already matches this and can be uploaded as-is. |
| Screenshots | 1280×800 PNG | at least 1, up to 5 | Full bleed, square corners, no padding. Five is what the Store recommends. |
| Small promo tile | 440×280 | yes | Without it the item sorts below items that have one. Avoid text; it gets shrunk. |
| Marquee | 1400×560 | no | Only used for editorial placement. Skip it. |

The screenshots and the tile are generated rather than made by hand:

```bash
.venv/bin/python scripts/e2e_server.py --port 8099    # seed a purchase, see the README
cd apps/extension && npx vite --mode e2e --port 5199
node scripts/extension_listing_screenshots.mjs ./out  # five 1280x800 PNGs
node scripts/extension_listing_tile.mjs ./out         # the 440x280 tile
```

**The row titles in the screenshots are sample text, not captures.** The panel,
its layout and every state shown are real; the article titles and word counts
are written into the rows before the shot is taken. The alternative was tried
and is wrong twice over: the deterministic double answers every URL with the
same title, so three rows carry three copies of one placeholder — and real
pages both refuse datacenter traffic (which is the extension's own documented
limitation) and would put another site's article titles in 立言阁's promotional
material. Edit `SAMPLES` in the script to change them.

---

## 5. Store listing tab

| Field | What goes in it |
| --- | --- |
| **Item name** | Taken from the manifest: 立言阁浏览器插件 |
| **Short description** | Taken from the manifest, ≤132 characters: 把正在读的页面收集为来源，创建一个立言任务。 |
| **Detailed description** | Yours to write. The one paragraph worth leading with: 插件把你正在读的那个页面的**网址**发给立言阁，由立言阁去抓取正文 —— 插件本身从不读取网页内容。 |
| **Category** | Productivity → Workflow & Planning |
| **Language** | 中文 (简体) |

The description is the first thing a reviewer reads, and "single purpose that is
narrow and easy to understand" is a policy rather than a suggestion. Say what
the extension does and stop; a list of unrelated benefits is what a single
purpose violation looks like.

---

## 6. Privacy tab

This is the tab that decides how long the review takes. Every field below is
answerable from the code, and the answers are already written down — the
浏览器插件 section of `/privacy` and `apps/extension/manifest.ts` are the source.

**Single purpose** — one or two sentences. Write it in English; the review team
reads English.

> Collects the URL of a page the user is reading as a source for a new writing
> task in 立言阁 (liyan), and creates that task. Nothing else.

**Permission justifications.** One per item in the manifest, in English:

- **activeTab** — "Reads the URL and title of the active tab, and only after
  the user clicks the extension's toolbar icon, so that the page they are
  reading can be submitted as a source. The extension has no content script and
  never reads page content."
- **storage** — "Stores the signed-in session and the id of the in-progress
  task-creation session in `chrome.storage.local`, so that closing the popup —
  which destroys it — does not log the user out or lose sources they have
  already collected."
- **Host permission, the API** — "The extension's own backend. Every request the
  extension makes goes here: sign-in state, submitting a source URL, and
  creating the task."
- **Host permission, Supabase** — "The extension's identity provider, used for
  the email one-time-code sign-in. No other host is reachable."

If asked why the hosts are declared rather than handled by CORS: the API keeps
an origin allowlist, an extension's origin is its id, and the id does not exist
until publication — so one build cannot work in every environment any other way.

**Remote code: No.** Every line of JavaScript is inside the package. There is no
`eval`, no `new Function`, and no remotely hosted script — Manifest V3 forbids
it and the build does not do it. Network calls carry data, not code, which is
not remote code and should not be declared as such.

**Data usage.** Declare these four, and certify all three statements:

| Category | Why |
| --- | --- |
| Personally identifiable information | The email address the user signs in with. |
| Authentication information | The session token, stored locally and sent with each request. |
| Web history | The URL of the page the user chose to collect. It is one page they picked, not a browsing history — but it is the address of a page they visited, and that is what this category covers. |
| Website content | The extension itself never reads it, but it is what asks 立言阁 to fetch the page, and the text ends up stored under the user's account. Declaring it and explaining the mechanism is defensible; withholding it and being read as under-disclosing is not. |

The three certifications — not selling to third parties, not using data for
purposes unrelated to the single purpose, not using it for creditworthiness or
lending — are all true and can be checked.

**Privacy policy URL** — `https://<工作台>/privacy`.

---

## 7. Distribution tab

- **Visibility: Unlisted.** Reviewed like any other item, absent from search and
  from category browsing, installable by anyone with the link.
- **Regions** — all, or 中国大陆 plus wherever your users are. This is not a
  gate on who can use 立言阁; sign-up is open, and 额度 are the only gate.
- **Paid?** No. 额度 are bought in 工作台, and the extension only links there.
  Do not declare a payment here.

---

## 8. Test instructions — do not leave this blank

Sign-up is open — a reviewer can create an account with a code sent to their
own mailbox — but URL 来源 require a 付费用户, so a cold install still ends at
尚未购买额度 partway through. An extension whose function cannot be verified is a
common rejection, so say what is reachable and what is not:

> Anyone can sign up for 立言阁 with an email code; collecting URL 来源 requires
> a paid account, so the extension cannot be exercised end to end without
> credits. The attached recording shows the complete flow — sign-in, opening a
> basket, collecting three pages, and creating the task. We are glad to credit
> a reviewer account on request.

Attach a screen recording of the whole flow. It is what most often gets a
login-gated extension through without a round trip.

---

## 9. Submit

**Submit for review**, and choose whether to publish automatically on approval
or hold it (you get up to 30 days to publish manually). For a first release,
holding it is worth it — it lets you look at the live listing before anyone can
install it.

Then wait. Most items are reviewed within a few days; a few weeks is possible,
and after three weeks it is worth contacting developer support. A first item
from a new publisher is on the slower end regardless of what it asks for.

While it is pending you cannot upload a new package. Fix nothing and submit
nothing until it resolves.

---

## 10. If it is rejected

The rejection names a policy section. Read that section rather than guessing,
fix the specific thing, bump the version, and resubmit — a resubmission is a new
review, not an appeal. If the rejection is wrong, the dashboard has an appeal
form; use it instead of resubmitting unchanged, which reads as circumvention.

The two most likely rejections here, and what to do:

- **Functionality could not be verified.** Credit a reviewer account and put
  the credentials in Test instructions.
- **Data disclosure does not match the privacy policy.** The two have to agree.
  `/privacy` and section 6 above are written to say the same thing; if you
  change one, change the other.

---

## 11. Every release after the first

1. Merge the change.
2. `npm run test:extension && npm run lint:extension && npm run typecheck:extension`
3. Walk the panel in the harness.
4. Bump `apps/extension/package.json`.
5. `npm run package:extension`, and read the manifest that comes out.
6. Upload the zip, review the listing for anything the change made untrue,
   submit.

**Never widen `permissions` or `host_permissions` casually.** A wider install
surface disables the extension for every existing user until each of them
re-accepts the new warning. `apps/extension/manifest.test.ts` pins the current
surface so that widening it takes an edit to a test and a reason.
