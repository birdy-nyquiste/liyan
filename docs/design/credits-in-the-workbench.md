# 额度 in the workbench

What a user sees of the 额度 system, and why each part is shaped that way.
`docs/operations/credits.md` is the other half: what things cost, and how 额度
are held and settled. This page never restates a number from it.

## The estimate is not a quote

Every act that spends 额度 is estimated before it starts. That estimate is
**internal**. It is compared against 剩余额度 to decide one thing — whether the
work begins or the user is told there is not enough — and it is never shown.

This is worth stating plainly because the alternative is so tempting. A quoted
price invites the arithmetic that follows it: the 预扣 settles down and rarely
to the quoted figure, so a user shown "最多 118" and charged 26 has been given a
number whose only job was to be wrong. Refusing to publish it costs a user who
is short the ability to see *how* short — a real loss, accepted deliberately —
and buys a product that never has to defend a figure it did not mean.

It also means the API grows nothing. There is no estimate endpoint and no
`estimated_credits` on any response. The work is attempted, the server compares,
and a refusal comes back as **402** with 额度不足. The whole feature is one
status code.

## Nothing is predicted beyond the job being asked for

A task's spend has a shape — captures, then analyses, then an article — and it
is tempting to warn at confirmation that the 额度 left will cover the analyses
but not the article that usually follows.

立言阁 does not do this. The user has not asked for an article yet, and may
never. Every job that spends 额度 is estimated and checked **when it is asked
for**, against the balance at that moment, and never on behalf of a job nobody
has requested. Guessing at intent to spend somebody's balance early is worse
than the outcome it avoids.

## One page

**`/account`**, holding all three of the things a user has to do with 额度:
see what is left, see where it went, and buy more. Not three pages and not a
modal — the workbench has already decided this shape once, when 发布 became a
page rather than a floating card.

Its entry is a fourth button in the sidebar's account group, beside 主题, 语言
and 退出登录. That group already renders a label with a value beside it, so the
balance rides there:

    额度        7,842

A bare integer. No "≈ N 篇文章" reading: that would come from a median, and the
people likeliest to lean on it are the ones working with long 来源, for whom it
is most wrong. A number that is exactly right beats a sentence that is
approximately helpful.

The consequence of living behind the account toggle is that a user does not
watch their balance while they work — they meet it at a refusal. That is
consistent with the rest of this page: the estimate is the server's business,
and the moment it matters is the moment work is asked for.

## 额度不足

Never a bare failure, and never a figure:

> 额度不足，购买后可继续。

with 购买额度 beside it, going to `/account`. A refusal a user cannot act on has
told them off rather than told them something.

## URL and file 来源 are visibly locked

Two of the three 来源 tabs need 额度 that has been bought. They are **not
clickable** for a user who has none, and they are **not hidden or silent**
either.

Hiding them makes the product look smaller than it is; a paid capability nobody
can see is one nobody can want. Disabling them with no reason is worse — a dead
control that explains nothing is a bug as far as the user knows.

So both tabs stay in place, carry a lock, and are accompanied by a line that
says what unlocks them and a 购买额度 button that goes to `/account`.

They use `aria-disabled` rather than `disabled`, so they keep their place in the
tab order and are announced rather than skipped, with the unlock line associated
by `aria-describedby`. A locked control a screen reader never mentions is hidden
after all. `docs/operations/accessibility.md` governs the rest.

## Buying, and the return that beats the webhook

Fulfillment happens on the Stripe webhook, deliberately — a user who closes the
tab has still paid. But Checkout also redirects them back, and that redirect
frequently arrives first: Alipay and WeChat Pay settle late by design.

A return state that simply reads 剩余额度 therefore shows the old number, and
reads as a payment that failed.

So it polls until the balance changes, and **its timeout is not an error**:

> 支付已收到，额度稍后到账。你可以先离开这里。

Never 支付失败. The money has left their account. Of everything this product
could say at that moment, that is the worst.

## 使用记录

One section of `/account`, one row per Execution, newest first: what it was,
when, and what it came to. The 预扣 and the settlement sit on the same row,
because the point of showing it at all is that the two differ and the difference
is explained.

    分析来源《朝鲜半岛局势综述》   进行中    预扣 28
    分析来源《关税政策全文》       已完成    26（预扣 28，结算 +2）
    抓取网页 reuters.com/…        已完成    3
    生成文章                      失败      0（预扣 24，结算 +24）

The failed run reading `0` is why this page exists in this form. A balance that
moved and then moved back, with nothing saying why, is the thing users write in
about.

This is also the one place a user can work out what things cost — not from a
quote before the fact, but from what they were actually charged after it.

## Copy and locale

Both the strings above and their English counterparts, in the same bilingual
shape as the rest of the workbench.

Two patterns coexist today: `AppShell` holds a `copy = { zh, en }` object, while
`TaskCreationSession` calls `t("中文")` with the Chinese source string. New
chrome — the sidebar button, the `/account` page — follows `AppShell`. New copy
inside an existing component follows whatever that component already does. A
file that does both is worse than either.

## What waits for stage 3

A deferred run holds its 预扣 while it waits for a provider slot, so its
使用记录 row reads 等待中 rather than showing a bare 预扣. Without it, a busy
period looks like 额度 taken for work that stopped. Nothing else here changes.
