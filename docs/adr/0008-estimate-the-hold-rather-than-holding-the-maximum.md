# 预扣 estimates the cost rather than holding the maximum

额度 are 预扣 before a 知言 or 立言 run at what it is *expected* to cost, and
结算 against the real cost when it finishes. Most of that estimate is counted
rather than guessed — the input is in hand before the request is sent — and the
two predicted terms, output length and 知言's search injection, are fitted from
measurements as functions of that known input.

A balance can therefore occasionally end a run slightly below zero. That is
accepted and monitored rather than prevented.

The alternative was to 预扣 a modelled worst case, which makes a non-negative
balance arithmetic. We rejected it for two reasons. It does not actually deliver
the certainty it appears to: `max_output_tokens` bounds output and a search cap
bounds how many searches run, but the tokens DeepSeek injects per search
*result* are the provider's choice and no parameter constrains them, so the
"maximum" is a model too. And it is expensive in the common case — a short 来源's
worst case runs about 1.6× its typical cost, so every ordinary run would hold
half again what it needs, refusing work users can comfortably afford in order to
prevent an overshoot a decent estimator makes rare.

So the target is a rate rather than an invariant. Overshoots should be rare
enough to be unremarkable, and the thing that keeps them rare is the quality of
the estimator, not the size of the cushion.

## Consequences

- The estimator's parameters are measurements, not constants: they must be
  refitted from recent runs, or they go stale when the provider changes how much
  it injects.
- The three operations are not equally predictable. 立言 has no tool access and
  so no injection term at all; 知言 over a long 来源 is ~90% counted; 知言 over a
  short 来源 is the only hard case, and also the cheapest place to be wrong.
- Two rates need watching — how often actual exceeds 预扣, and how often a
  settlement leaves a balance negative. Both are computable from 使用记录 alone,
  and neither has a target until the shadow meter has run.
- A user in deficit starts nothing new, and their next 购买 clears the shortfall
  before it adds anything. No separate collections path exists or is wanted.
- 立言阁 does not absorb overshoot as a matter of course. The charge is what the
  work cost, not what was guessed.
