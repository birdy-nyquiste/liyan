# 立言阁浏览器插件

The extension whose whole job is to turn pages a user is already reading into
the 来源 of a new 立言任务. Its name is 立言阁浏览器插件; this page refers to it
as the extension, the way these pages call 工作台 the workbench. Here is what it
is and why it is shaped this way. `docs/operations/limits.md` owns the numbers
it runs into, and `credits-in-the-workbench.md` owns what 额度 mean; neither is
restated here.

## What it does not do

**It does not read the page.** The extension sends the current tab's URL and
the server fetches it, exactly as the workbench's URL 来源 does. A content
script reading the DOM would capture pages the server cannot — paywalled,
login-gated, rendered after interaction — and that is a real capability, but it
is a different product: it needs its own 来源 kind, its own metering, and broad
host permissions at install. None of that is bought here.

The consequence is worth naming rather than discovering: the extension can only
capture what the server could already have captured. On a page that refuses
datacenter traffic, the extension fails where the user's own browser succeeds,
and the user is standing right there watching it happen.

**It does not add 来源 to an existing 立言任务.** That path is a 来源编辑会话,
whose save takes the complete source list and is refused while 知言 or 立言 is
running. Rebuilding that state machine in a 360px panel would fork the rules
into a second client. The extension creates tasks; the workbench edits them.

**It does not sell 额度.** A user who has not bought any is told so and sent to
the workbench. One purchase surface, and it is the one that already exists.

## The basket

The extension is not one-page-one-task. A user reads three pieces about the
same thing and wants one 立言任务 holding all three, and that is what a
任务创建会话 already is: up to three 来源 confirmed together.

So the flow has a container:

1. **新建任务** opens a basket. It sends nothing — it generates a
   `client_session_id` and stores it. The session exists on the server only
   when the first 来源 is submitted to it, so opening a basket and changing
   your mind leaves nothing behind.
2. **添加当前页面** submits the current tab's URL into that basket. The
   extension polls the session, not each 来源: one request returns every item's
   status, title, and length, which is exactly what the list renders.
3. **确认创建任务** confirms the whole basket. The task is created, 知言 is
   queued, the stored session id is dropped.

The two buttons sit at the bottom of the panel and never move. What changes is
what they say and whether they are live.

Nothing above needs a new endpoint. The 任务创建会话 was built for a client
that collects before it commits; the extension is a second such client.

### One basket, one session id

The session id is per basket, not per install and not per capture. Per capture
would strand every unconfirmed 来源 as an orphan. Per install would let a
basket confirmed today sweep up something captured last week, because
confirmation demands every unconfirmed 来源 in the session and takes no subset.

That same rule is why removing an item is a delete rather than a checkbox. A
来源 the user does not want in this task cannot be left out of the request; it
has to stop existing.

### Warnings ride on the item

A 来源 the server marks with a warning shows that warning in the list, on the
row it belongs to, and the confirm request accepts it. There is no separate
"are you sure" step.

This is not the guard being waived. The guard exists so that a thin 来源 is
never analyzed without the user having seen that it is thin, and a warning
sitting on the row directly above the button they are about to press satisfies
that better than a modal they will dismiss. What the guard forbids is
auto-accepting a warning the user was never shown; that is not what happens
here.

## The screens

Twelve, numbered because the issues cite them. A screen is listed when the
panel has to behave differently on it, not when it merely looks different.

**Signed out**

1. **未登录** — `AuthPanel`'s email screen, in a 360px column.
2. **输入验证码** — its OTP screen, keeping 换个邮箱 and 重新发送. In a panel
   there is no reload to fall back on when the address was mistyped.
3. **已登录，尚未购买额度** — `PAID_ONLY` in the server's own words, and a link
   to the workbench's account page. Decided before the first render.

**Collecting**

4. **主屏** — one action: 新建任务. Sends nothing.
5. **空篮子** — both bottom buttons are in place from here on and never move.
   确认创建任务 is dead: a task needs at least one 来源.
6. **正在抓第一条** — the row appears immediately and advances on its own. The
   user can leave for the next tab.
7. **两条，其中一条偏薄** — the warning sits on its row. The confirm button is
   live and its label carries the count.
8. **装满了** — 添加当前页面 dead, with the reason where the button is.
9. **已创建** — the task's link, and the fact that 知言 has started. The basket
   is gone.

**Interrupted, or refused**

10. **有一条抓失败了** — confirm is dead until the failure is removed, and the
    panel says so rather than leaving a grey button unexplained. The row also
    says the failure cost nothing.
11. **关掉之后再打开** — the basket is still there, each row carrying its age,
    and the oldest carrying how long it has left.
12. **这一页加不了** — 添加当前页面 dead: not a public URL, or already in this
    basket. Both are known before the click.

## Signing in

The workbench's sign-in is reused rather than rebuilt: same component, same
strings, same 仅限受邀用户 framing, in a 360px column. Email OTP is what makes
this cheap — a six-digit code needs no redirect URI, no deep link, and no
callback page, which is where extension auth usually goes wrong.

One change belongs in the workbench for this to work: `SupabaseAuthProvider`
constructs its client with the default storage, and `localStorage` does not
exist in an extension's service worker. The storage becomes an injected
dependency — the workbench passes nothing, the extension passes an adapter over
`chrome.storage.local`. Forking the provider would leave two copies of the
refresh behaviour, and the refresh behaviour is the part that is easy to get
wrong.

That behaviour ports over unchanged, and for the same reason it exists: the
token is fetched before each request rather than cached, because a panel left
signed in overnight would otherwise send a dead one.

## What the panel has to say on the server's behalf

Every refusal below is already enforced. The panel's job is to arrive at them
early, or to render them in the server's own words.

**Not a 付费用户.** Checked when the panel opens, so a user who cannot capture
sees why instead of a button whose only outcome is a refusal. For a newly
installed extension this is the default first screen after sign-in, which is a
product fact rather than an edge case.

**Not a public URL.** `chrome://`, `file://`, and internal hosts are rejected by
normalization. The panel knows the tab's URL before the user clicks, so the
button is disabled with the reason beside it.

**Already in this basket.** The server refuses a duplicate URL within a
session. The panel knows the basket's contents, so this too is a disabled
button rather than a failed request.

**Three 来源 per basket**, and **the execution ceiling**, which the extension
shares with everything else the user has running — a workbench confirmation of
three 来源 can put the next capture over it. Its message is written for a user
and is shown unaltered.

**A failed capture blocks the basket.** Confirmation requires every 来源 in the
session to be ready, so one failure stops the whole thing until it is removed.
The panel says that where the disabled button is, because the alternative is a
grey button with no explanation.

A capture that fails costs nothing: work that produced nothing settles to zero.
A capture that succeeds and is never confirmed costs what it cost. The panel
should be more careful about the second case than the first, which is the
opposite of the instinct.

## What the panel remembers, and whose words it uses

The server answers with codes and with English. Both are deliberate, and both
mean the panel has work to do before anything reaches a reader.

A `warning` and a `failure` each carry a code and a message, and the message is
written for whoever reads the logs. 工作台 already keeps a sentence per code for
the person looking at the screen, and that table is what both clients read —
two wordings for one rule is how they come to disagree. The same goes for
naming a warning: it is named by the code it actually carries, never by the
commonest one, because a 23,000-character article can come back `warning` for
having no title and being told 正文偏薄 about it is simply false.

The refusals are the exception, and stay verbatim. 额度不足 and the per-user
ceiling arrive already written for a user, and rewording them would be the
panel disagreeing with the server about why it said no.

Two things the server never sends back, which the panel keeps for itself:
**when** each 来源 was added, and **which page** it was. A settled 来源 carries
no timestamp and its Execution is gone; a `provenance` exists only once a fetch
has succeeded, so a failed 来源 has none at all — and which page failed is the
one thing its row must say. Keeping both locally is right regardless: the
basket exists only in this browser, so there is nowhere else they could serve.

## The holes this leaves

**A basket kept overnight loses items.** Cleanup ages each unconfirmed 来源 on
its own timestamp, so a basket filled across two days can quietly become a
basket of one. The panel shows each item's age, which makes the loss visible
but does not prevent it. Preventing it means touching one 来源 in a session
extends the rest, and that is a server decision, not a panel one.

**The extension and the workbench cannot see each other's baskets.** Both read
sessions by `client_session_id`, and the workbench's lives in `localStorage`
under its own key. A 来源 captured in the extension is invisible in the
workbench's creation page and vice versa, and the same URL captured in both
becomes two tasks with the same content.

Sharing the session id between them would fix the visibility and break
something worse: a confirmation from either client would sweep up whatever the
other was still drafting. The fix, when it is worth doing, is a read that is
not keyed by session — every unconfirmed 来源 this user has — which the
workbench can show and the extension can recover from. It is not required for
the extension to work, and it repairs a hole the extension did not open: a user
who clears `localStorage` today already strands whatever was in their basket.

## Install-time surface

`activeTab` and `storage`, plus host permissions for 立言阁's own API and its
Supabase project. No content scripts, no permission over any site the user
browses, and no background page doing work.

The two host permissions are not a widening of what the extension may read;
they are how it is allowed to call its own servers. The API keeps a CORS
allowlist, and an extension's origin is its id — which differs between an
unpacked build and a published one, and is not known at all until publication.
Asking for the two hosts by name lets one build work in every environment
without the server having to be told who is calling.

Because those addresses differ per environment, the manifest is generated at
build time from the same `VITE_` values the workbench reads, rather than
committed with a placeholder in it.
