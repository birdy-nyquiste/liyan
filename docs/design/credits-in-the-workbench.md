# 额度 in the workbench

What a user sees of the 额度 system, and why each part is shaped that way.
`docs/operations/credits.md` is the other half: what things cost and how 额度
are held and settled. This page never restates a number from it.

Two decisions here reach past the interface and into the API. They are first.

## The estimate rides on responses the workbench already polls

Quoting a cost before work starts means the server can produce an estimate
**without creating an Execution**, which nothing in `credits.md` required.

The obvious shape is an endpoint — `POST …/estimate`. It is the wrong one. It
doubles the round trips on the busiest path, and it lets the quote drift out of
step with the answer beside it: a client can be told it may confirm and told a
price by two different requests, and reconcile them itself.

So `estimated_credits` goes on the responses that already carry the decision.
The 任务创建会话 response carries `can_confirm`; the estimate belongs next to it,
computed in the same breath, so the two cannot disagree. The same for a 立言
target and for a 知言 retry, whose `RetryState` is already exactly this kind of
answer.

This follows ADR-0005's reasoning rather than inventing its own: the allowance
is derived server-side on every request, so a reload, a second tab, or a direct
`POST` cannot disagree with it. A price is the same sort of fact.

## The purchase return will beat the webhook

Fulfillment happens on the Stripe webhook, deliberately — a user who closes the
tab has still paid. But Checkout also redirects them back, and that redirect
frequently arrives first. Alipay and WeChat Pay settle late by design.

A return page that simply reads 剩余额度 therefore shows the old number, and
reads as a payment that failed.

So the return state polls until the balance changes, and **its timeout is not an
error**:

> 支付已收到，额度稍后到账。你可以先离开这里。

Never 支付失败. The money has left their account. Of everything this product
could say at that moment, that is the worst.

---

## The number

**剩余额度, as a bare integer**, in the sidebar rail — not inside the collapsible
account group beside theme and language. It is something a user needs *before*
starting work, and a number behind a toggle cannot do that job.

No "≈ N 篇文章" beside it. That reading would be drawn from a median, and the
people most likely to lean on it are the ones working with long documents, for
whom it is most wrong. A number that is exactly right beats a sentence that is
approximately helpful.

Quiet when healthy. Prominent when low — the same number, given weight, not a
different number given an explanation.

## When a quote interrupts, and when it does not

Every act that spends 额度 shows its cost before it happens. Only some of them
stop to ask.

A routine task is a small fraction of an 额度包, and a dialog for it is friction
on the main path. A long-document task can be a third of one, and clicking
through that unannounced is a real grievance.

    创建任务（最多 118 额度）      ← inline, and that is all

Past roughly a fifth of 剩余额度, the existing `ConfirmDialog` names the number
and asks. Interruption proportional to what is at stake, rather than a policy of
always or never.

The word is 最多. The 预扣 is an estimate that settles down and never up, so
"最多" is true and "约" is not.

## The way a task can strand someone

The spend has a shape: three captures, then three 知言 runs, then one 立言
generation. The article is the last and smallest step, and it is the thing the
user actually came for.

Checking only the immediate act permits the worst outcome in the product: 额度
spent on every analysis, and nothing left to write the article they were for.

Confirmation does not *refuse* on this — a user may never generate an article,
and refusing work they can afford because of work they have not asked for is
overreach. But it warns, at the moment the choice is still free:

> 剩余额度足够完成分析，但可能不足以生成文章。

## Gating without hostility

Two of the three 来源 tabs are for 付费用户. Neither is hidden and neither is
disabled.

Hiding them makes the product look smaller than it is; a paid capability nobody
can see is one nobody can want. Disabling them without a reason is worse — a
dead control that says nothing is a bug as far as the user knows.

They stay clickable. Choosing 公共文章链接 or 上传文件 without having bought 额度
explains what the tab does and how to reach it, in place, with a link to
`/credits`. The tab teaches instead of refusing.

## 额度不足

Never a bare failure. The refusal names both numbers and offers the way out:

> 额度不足。本次最多需要 118 额度，剩余 40。

with 购买额度 beside it. A user who cannot act on a refusal has been told off
rather than told something.

## 使用记录

One row per Execution, newest first, showing what it was, when, and what it
came to. The 预扣 and the settlement are on the same row, because the point of
the page is that the two are different and the difference is explained:

    分析来源《朝鲜半岛局势综述》   进行中    预扣 28
    分析来源《关税政策全文》       已完成    26（预扣 28，结算 +2）
    抓取网页 reuters.com/…        已完成    3
    生成文章                      失败      0（预扣 24，结算 +24）

A failed run reading `0` is the whole reason this page exists in this form. A
balance that moved and then moved back, with nothing saying why, is the thing
users write in about.

## Routes

Pages rather than floating cards, following where the workbench has already
gone with 发布:

| Route | Holds |
| --- | --- |
| `/credits` | 剩余额度, the 额度包, purchase, and the return-from-Stripe state |
| `/credits/history` | 使用记录 |

`/credits` is reachable from the sidebar number, from every 额度不足 refusal,
and from the 来源 tabs a 付费用户 gets.

## Copy and locale

Both the strings above and their English counterparts, in the same bilingual
shape the rest of the workbench uses.

Note that two patterns coexist today: `AppShell` holds a `copy = { zh, en }`
object, while `TaskCreationSession` calls `t("中文")` with the Chinese source
string. New chrome — the sidebar number, the routes — follows `AppShell`. New
copy inside an existing component follows whatever that component already does,
because a file that does both is worse than either.

## What waits for stage 3

A deferred run holds its 预扣 while it waits for a provider slot, so its
使用记录 row must read 等待中 rather than showing a bare 预扣. Without it, a busy
period looks like 额度 taken for work that stopped. Nothing else here changes.
