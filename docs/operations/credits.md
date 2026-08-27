# 额度

What a user buys, what it costs 立言阁 to serve, and the two equations that
connect them. `docs/design/credits-in-the-workbench.md` is the other half: what
a user sees of all this, which is deliberately very little. Everything here is one of three things: a rate quoted by a
supplier, a measurement, or an assumption. The assumptions are marked, because
several of them are currently guesses and the difference matters to the margin.

## The whole system, in one constant

    credits = ceil(cost_usd × K)          K = 2,000

`K` ties one 额度 to 立言阁's own cost and does not move. One 额度 is worth
$0.0005 of what serving the work costs — permanently, whatever the margin is.

Margin lives in a separate number: **how much 额度 one dollar buys**.

    credits_per_dollar_paid = K × (1 − margin) = 400

Splitting it this way means changing the margin later re-prices nothing a user
sees. A 知言 run costs the same 额度 at 50% margin as at 80%; only
the 额度包 shrinks. And when a provider cuts its prices, actions get cheaper in
额度 on their own, and an 额度包 goes further without anybody deciding it should.

## The setting

| | |
| --- | --- |
| K | 2,000 额度 per $1 of cost |
| 额度 per $1 paid | 400 |

Three 额度包, all at the same 400 额度 per dollar:

| 额度包 | 额度 | Cost it can consume | Stripe fee | **Net profit** | |
| --- | --- | --- | --- | --- | --- |
| $5 | 2,000 | $1.00 | $0.50 | **$3.50** | 70.1% |
| $20 | 8,000 | $4.00 | $1.08 | **$14.92** | 74.6% |
| $50 | 20,000 | $10.00 | $2.25 | **$37.75** | 75.5% |

Stripe charges 2.9% + $0.30 on cards, Alipay, and WeChat Pay alike, plus 1% for
currency conversion — which a payer in China settling a USD charge will incur,
so the table assumes it. The fixed 30¢ is why the small 额度包 nets five points
less than the large one at an identical 额度 rate; that gap is the price of
having a cheap way in, not a pricing mistake.

Break-even against ~$37/month of fixed infrastructure (API, worker, beat,
Redis, Postgres) is **two or three $20 额度包 a month**. Fixed cost is deliberately not
loaded into any per-operation price: the per-unit share depends on a volume
nobody knows yet, so a fee built on a guessed volume is wrong at every volume
except the guess. It comes out of margin, and this is the sentence that says so.

## Two meters

Everything 立言阁 does costs money in one of two shapes, so there are two cost
functions and one conversion.

### ① Source capture — flat, per 来源

Covers the non-LLM marginal cost of having a 来源 at all: Chromium fetching a
URL, PDF and DOCX parsing, and R2 storage for as long as the 来源 is kept. Not
the worker seconds of its 知言 run — those are that run's own, and are metered
there.

    capture_credits = CAPTURE_CREDITS = 3

Flat, and the same for a pasted 来源 as for a 10MB PDF, because the cost really
is nearly flat — and small:

| | URL, typical | File, typical (2MB) | File, worst (10MB, 60s) |
| --- | --- | --- | --- |
| Fetch / parse worker time | $0.000041 | $0.000027 | $0.000162 |
| R2 storage | — (URL 来源 never touch R2) | $0.00036 | $0.0018 |
| **Total** | **$0.000041** | **$0.00039** | **$0.0020** |
| Computed 额度 | 1 | 1 | 4 |

Length is paid for in ②, where it genuinely scales, and charging for it twice
would be charging for it once wrongly.

The fee is set to cover **the tail rather than the average**: three 额度 nearly
covers the largest file this system accepts, so the biggest uploads are
subsidised by a fraction of a cent instead of by a second term in the equation.
An ordinary 来源 pays more than it costs, and that is the price of the whole
thing being one number nobody has to think about.

### ② 知言 and 立言 — measured tokens

    cost_usd = (miss_tok × 0.44 + cached_tok × 0.014 + out_tok × 1.32) / 1e6
    credits  = ceil(cost_usd × K)

One equation for both operations; only the token counts differ.

## Supplier rates

**DeepSeek `deepseek-v4-flash`**, per 1M tokens:

| | Off-peak | Peak |
| --- | --- | --- |
| Input (cache miss) | $0.22 | $0.44 |
| Input (cache hit) | $0.007 | $0.014 |
| Output | $0.66 | $1.32 |

Peak is 01:00–04:00 and 06:00–10:00 UTC on weekdays, which is 09:00–12:00 and
14:00–18:00 in China. That is the working day of the people this product is
for, so **every number on this page uses peak rates**. Costing at the off-peak
rate would halve the apparent cost of the hours when the work actually happens.

DeepSeek's web search bills no separate fee — results arrive as ordinary input
tokens. It is therefore not a line item, but it is the least predictable part
of a 知言 run's input, which is what §What bounds the model is about.

**Render Starter** (API, worker, beat): $7/month, 0.5 vCPU, 512MB, so
**$0.0000027 per second**. **Cloudflare R2**: $0.015/GB-month, egress free.

## What this comes to

| Action | Cost | 额度 | To the user |
| --- | --- | --- | --- |
| Capture one 来源 | $0.00004–0.002 | 3 | $0.008 |
| 知言, short 来源 (2k chars) | $0.0138 | 28 | $0.070 |
| 知言, long 来源 (500k chars) | $0.1482 | 297 | $0.743 |
| 立言 article | $0.0122 | 25 | $0.063 |
| **Typical task** (3 short 来源 + article) | $0.054 | **118** | **$0.30** |
| Long-document task | $0.458 | 925 | $2.31 |

Charged per act rather than over the total, because that is how it happens: each
Execution rounds up on its own.

A $20 额度包 is therefore about **67 typical tasks** or **8 long-document ones**.

Every figure here is computed by `rate_card.py` and asserted by
`tests/test_rate_card.py`, so a rate that moves without this page moving with it
fails a test rather than quietly becoming untrue.

## Buying 额度

Stripe Checkout in `payment` mode, not `subscription`. That is not a
preference: WeChat Pay cannot be saved for off-session use and so cannot back a
Stripe subscription at all, and Alipay's recurring support is narrow and
regional. Selling 额度包 rather than a monthly plan is what makes the payment
methods this product's users actually have available to it.

One Checkout Session offers card, Alipay, and WeChat Pay together. WeChat Pay
additionally needs a `client` parameter naming the surface (`web`), and renders
as a QR code.

Four rules, each of which is a way this goes wrong quietly:

**The 额度 amount is derived on the server from the Stripe Price.** Never from
anything the client sent, and never from session metadata a client could have
influenced. Metadata carries the user's id so fulfillment knows whom to credit;
the amount comes from a server-side mapping of Price ID to 额度.

**Fulfillment happens on the webhook, never on the success redirect.** A user
who closes the tab after paying has still paid. The redirect is a nicety; the
webhook is the transaction.

**Both completion events are handled.** `checkout.session.completed` covers the
common case, and `checkout.session.async_payment_succeeded` covers Alipay and
WeChat Pay settling late — with `..._failed` as its counterpart. Fulfilling only
the first silently loses the delayed ones.

**Redelivery is a primary-key violation, not a double credit.** Stripe retries
webhooks, so a `stripe_events` table keyed on the event id is written *inside
the same transaction* as the 购买 entry. A repeat delivery then collides and is
swallowed rather than crediting twice. `charge.refunded` and
`charge.dispute.created` write a clawback through the same path.

Charges are in USD. A payer in China sees their wallet convert, and 立言阁 sees
the 1% conversion fee in the table above.

## What a new user gets

A new user is given 赠送额度 **once**, on signing up. There is no monthly refill:
the natural cadence of this product is one article at a time, and a standing
monthly grant is not retention, it is a standing bill against every account that
was opened and abandoned.

Until they buy 额度 they are not a 付费用户, which means their 来源 are ones they
paste. That boundary is structural rather than policed: a pasted 来源 is
normalized in the request that submits it and queues no Execution at all, so a
user who has never paid never reaches Chromium, never reaches the PDF parser,
and never occupies the heavy queue. The grant is exposed only to 知言 and 立言,
whose cost is metered like any other.

The **amount** is deliberately not written here yet. Sizing it means knowing
what one complete 立言任务 actually costs — three pasted 来源 at 3 额度 each, the
知言 runs over them, and one 立言 generation — and that figure is an assumption
above rather than a measurement. It is set at step 4 of the build order, from
the shadow meter, and not before.

## Assumptions, and how wrong they could be

Nothing below has been measured. They are the reason this page is reasoned
rather than measured, and `scripts/calibrate_costs.py` is how each one stops
being a guess. Until it has been run, every 额度 figure on this page inherits
whichever of these is furthest off.

| Assumption | Value | Confidence |
| --- | --- | --- |
| Chinese characters → tokens | 0.6 tok/char | Good |
| Instructions + report schema | ~2,000 tokens | Rough |
| Search results injected per 知言 run | ~15,000 tokens | **Weak — could be 3× either way** |
| 知言报告 output | ~4,000 tokens | Rough |
| R2 retention for amortisation | 12 months | A policy choice, not a measurement |

The search-result figure is the one that matters. It is the largest term in a
short 来源's cost, it is chosen by the provider rather than by 立言阁, and
nothing currently bounds it.

## Holding and settling

Two kinds of cost, so two treatments.

**Capture is deterministic.** Three 额度, known before anything runs, whatever
the 来源 turns out to be. There is nothing to estimate: it is charged outright
when the 来源 is admitted. A capture that fails produced no 来源, so it is
reversed in full and a retry charges again.

**知言 and 立言 are not.** Their cost is discovered by running them, so 额度 are
预扣 at admission at what the run is *expected* to cost, and 结算 when it
reaches a terminal state.

    结算 = 预扣 − actual        (positive returns the excess, negative collects
                                the shortfall)

The 预扣 is an estimate, not a ceiling. It is not clamped, and the charge is
what the work actually cost: a run that overshoots its estimate is billed at
what it was, not at what was guessed, because 立言阁 should not absorb its own
modelling error as a matter of course.

The consequence is that a balance can occasionally end a run slightly below
zero. That is accepted rather than prevented — see below for why the
alternative is worse — and it is handled by the simplest available rule: a user
whose 额度 are exhausted starts nothing new, and their next 购买 clears the
deficit before it adds anything.

A failed, cancelled, or swept run has an actual of zero and settles whole.

### Why not hold the maximum

The obvious way to make a balance provably non-negative is to 预扣 the worst
case the run could possibly cost. It was rejected, because for 知言 the worst
case is both unknowable and enormous.

Unknowable: `max_output_tokens` bounds output and a search cap bounds how many
searches run, but how many tokens DeepSeek injects per search *result* is the
provider's choice and no API parameter constrains it. Any "maximum" is
therefore itself a model — so holding one buys pessimism without buying
certainty.

Enormous: a short 来源's worst case is roughly 44 额度 against a typical 28.
Holding 1.6× of every run's cost means refusing work users can comfortably
afford, on every short 来源, permanently, to prevent an overshoot that a good
estimator makes rare. That is a bad trade for a product where the common case
is a short pasted 来源.

So the target is a **rate**, not an invariant: overshoots should be uncommon
enough to be unremarkable, and the mechanism that keeps them uncommon is the
estimator below.

### The estimator

Most of a run's cost is not estimated at all — it is counted. The 来源 text,
the 知言报告, and the 立言指令 are all in hand before anything is sent, so the
input tokens are known rather than guessed. Only two terms are predicted, and
one of them exists for exactly one operation.

**Output length** is unknown for both operations, because it is what the model
produces. It is well behaved: a 知言报告 is `strict` JSON against a fixed schema,
and both operations can be given a `max_output_tokens` bound.

**Search injection** is unknown for 知言 only. `zhiyan/deepseek.py` sends
`tools: [web_search]` with `tool_choice: "auto"`, so DeepSeek decides how many
searches to run and how much result text each contributes — arriving as
billable input that 立言阁 never sent. `liyan/deepseek.py` sends `tools: []` and
`tool_choice: "none"`, so 立言 has no such term.

Both predicted terms are functions of the known input, not constants. A longer
来源 yields more 事实结论 and so a longer 知言报告; longer reports yield a longer
article:

    预扣 = ceil( (known_input_tok             × R_in
                  + f_output(known_input_tok) × R_out
                  + f_search(known_input_tok) × R_in) × K )

`f_output` and `f_search` are fitted from what recent runs actually did, per
operation, and refitted as more accumulate — so the estimator tracks the
provider's behaviour rather than a snapshot of it taken once. Fitting them at a
high percentile rather than at the mean is the knob that trades a little
pessimism for far fewer overshoots.

The same measurements calibrate the character-to-token ratio, which is assumed
above and need not stay assumed: every run reports its real `prompt_tokens`
beside a 来源 whose length is already known.

### How much is actually at stake

The share of cost that must be predicted varies enormously with the shape of the
work, which is why one estimator behaves very differently across three cases:

| | Known exactly | Output | Search |
| --- | --- | --- | --- |
| 知言, long 来源 | **90%** | 5% | 5% |
| 立言 | **55%** | 45% | — |
| 知言, short 来源 | **11%** | 40% | 49% |

A long 来源 is nearly exact before it starts. 立言 rests on a single well-behaved
variable with no provider discretion in it. **知言 on a short 来源 is the only
genuinely hard case** — the 来源 is small, so the search results dwarf it, and
the term that dominates is the one DeepSeek chooses rather than the one 立言阁
sends.

That is also where an overshoot costs least. A 28 额度 estimate missing by ten
matters far less than a 297 额度 one missing by a hundred, and the hard case is
the small one.

### What to watch

Two numbers say whether the mechanism is working, and neither raises an alarm
on its own:

- **Overshoot rate** — how often `actual > 预扣`. Rising means the estimator's
  percentiles are stale, usually because the provider changed how much it
  injects.
- **Deficit rate** — how often a settlement leaves a balance below zero. This
  is the one users feel, and it should be a small fraction of the overshoot
  rate, since most overshoots land on a balance with room to absorb them.

Both are computable from the 使用记录 alone. Neither has a target yet, because
neither has been measured; step 4 of the build order is where they get one.

### The entries

| Kind | Sign | Written when |
| --- | --- | --- |
| 赠送 | + | Signup |
| 购买 | + | Stripe fulfillment |
| charge | − | A 来源 is captured |
| 预扣 | − | A 知言 or 立言 run is admitted |
| 结算 | ± | That run reaches a terminal state |
| clawback | − | Refund or payment dispute |

Remaining 额度 is the sum, read and never stored.

预扣 and 结算 key on the same `(target_type, target_id, attempt)` triple that
`Execution` already uses, which makes both idempotent under a unique index and
lets a 预扣 exist before its Execution does — which it must, because of the
next paragraph.

### Where the check happens

At the same entry points as `refuse_when_at_capacity`, called rather than wired
in as a dependency, for the same reasons its docstring gives.

One of those reasons applies with more force here. Confirming a 任务创建会话
queues one 知言 run per 来源, and `queue_initial_runs` deliberately runs after
the task transaction has committed so that a 知言 failure cannot roll back the
formal task. If the 预扣 were taken there, two concurrent confirmations could
both pass the check and the second could run out partway through its 来源,
leaving a 任务版本 with one report and two 来源 that were never queued — the
half-analyzed version the capacity ceiling exists to prevent. So **the whole
batch is 预扣 inside the confirming transaction**, before queueing is reached.
The same holds for saving a 来源编辑会话.

### Settling is reconciled, not remembered

A run reaches a terminal state down four paths: the worker succeeding, the
worker failing, a cancellation, and the stalled sweep in `stalled.py`. A 结算
that has to be remembered at each of them will eventually be forgotten at one,
and a forgotten 结算 silently strands a paying user's 预扣 — no error, no alert,
exactly the quiet failure `limits.md` is written against.

So a beat sweep beside `recover_stalled_executions` finds any terminal
Execution holding a 预扣 with no 结算 and writes one. The inline path may still
write it eagerly so the number moves while the user is watching; the unique
index makes the two safe together. A terminal path nobody remembers to wire
then leaks nothing.

## Two caps worth having anyway

Neither of these is load-bearing for correctness now that the 预扣 is an
estimate rather than a ceiling. Both are still worth adding, because they cut
the tail the estimator has to cover:

- `zhiyan/deepseek.py` sets no `max_output_tokens`, so a runaway generation is
  bounded only by the 300-second timeout. A cap turns the worst overshoot from
  unbounded into a known multiple.
- `ToolPolicy` is a single `web_search_enabled` flag, and its own docstring says
  the provider owns its search caps — so the number of searches, the least
  predictable term in the estimate, is currently DeepSeek's to choose.

Their values are set from the shadow meter at step 4, at a high percentile of
what runs actually do. Guessing them now would trade report quality against a
distribution nobody has looked at.

## Build order

The first three steps bill nobody and are where every guess above turns into a
measurement.

1. **Capture `usage`.** `provider_result` in both `zhiyan/deepseek.py` and the
   立言 equivalent parses the response and drops the `usage` block on the floor.
   Nothing in this repository has ever recorded a token.
2. **Add the caps** — `max_output_tokens`, and a search-call limit in
   `ToolPolicy`. Not required for correctness; they cut the tail the estimator
   has to cover.
3. **Record cost per Execution.** `started_at`/`finished_at` are already on
   `Execution`, so worker seconds need a rate table rather than instrumentation,
   and `search_actions` is already captured. Persist tokens, seconds, bytes,
   the rate-card version, and the resulting cost — and charge nobody.
4. **Calibrate.** `scripts/calibrate_costs.py` drives 知言 and 立言 over a corpus
   you choose and fits the assumptions above against what actually happened.
   Not shadow mode against real traffic: behind an allowlist there is barely
   any, and what there is would be whatever a few testers happened to paste. A
   corpus spread across lengths gives the same answers in an afternoon. Then set
   the 赠送额度 amount and the caps, and replace the assumptions table with
   measurements.
5. Ledger, 预扣, enforcement.
6. Stripe.

The free grant in particular cannot be chosen before step 4 without picking a
number for a task cost nobody has measured.

## Rates change

The rate card is versioned and stamped onto every cost record, so a historical
charge stays explainable after a price change.

What a rate change must not do is quietly revalue 额度 somebody already
holds. Raising the 额度 cost of a 知言 run means every existing balance buys
less than it did, with no event a user could see. So the rule is a one-way
ratchet: **a rate change may lower the 额度 cost of an operation and never
raise it.** If costs rise, the 额度包 price moves for new purchases instead.
