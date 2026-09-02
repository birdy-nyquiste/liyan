"""What 立言阁's suppliers charge, and what that comes to in 额度.

Every rate here is micros of one US dollar per *million* units of whatever it
measures — tokens, milliseconds of worker time, bytes retained. One divisor
serves all of them, and nothing needs a float: money in this system is integer
micro-dollars from the provider's invoice to the user's balance.

`docs/operations/credits.md` is where these numbers come from and what a credit
is worth. This module is only their application. DeepSeek charges two rates —
peak on weekday working hours, half that otherwise — and a run is costed at
whichever was in force while it ran. An estimate, having to guess, assumes peak.

`RATE_CARD_VERSION` is stamped onto every cost record so a charge stays
explainable after a rate moves. ADR-0009 governs how one may move: a change may
lower an operation's 额度 cost and never raise it, because 额度 already bought
are a promise about how much work they will do.
"""

from dataclasses import dataclass
from datetime import datetime

from liyan_server.provider_usage import ProviderUsage

#: Bump on any change to the numbers below, so historical costs stay readable.
#: 2 — a run is priced at the rate in force when it ran, rather than always at
#: peak. ADR-0009 permits it: it lowers what an off-peak operation costs in 额度
#: and raises nothing.
RATE_CARD_VERSION = 2

#: Every rate is quoted per this many units.
PER_MILLION = 1_000_000


@dataclass(frozen=True)
class ModelRates:
    """Micro-dollars per million tokens, in one of DeepSeek's two windows."""

    uncached_input: int
    cached_input: int
    output: int


@dataclass(frozen=True)
class ModelPricing:
    """What one model costs in each window.

    Both are written out rather than deriving one from the other. Off-peak is
    currently exactly half of peak for every rate DeepSeek publishes, and a
    `× 0.5` would encode that coincidence as a law — so the day the discount
    changes for one rate and not another, every cost would be quietly wrong
    with nothing to notice it. Two tables disagree loudly instead.
    """

    peak: ModelRates
    off_peak: ModelRates


MODEL_RATES: dict[str, ModelPricing] = {
    "deepseek-v4-flash": ModelPricing(
        peak=ModelRates(
            uncached_input=440_000,
            cached_input=14_000,
            output=1_320_000,
        ),
        off_peak=ModelRates(
            uncached_input=220_000,
            cached_input=7_000,
            output=660_000,
        ),
    ),
    "deepseek-v4-pro": ModelPricing(
        peak=ModelRates(
            uncached_input=1_320_000,
            cached_input=44_000,
            output=3_960_000,
        ),
        off_peak=ModelRates(
            uncached_input=660_000,
            cached_input=22_000,
            output=1_980_000,
        ),
    ),
}

#: The UTC hours DeepSeek charges peak in, on weekdays only: 01:00–04:00 and
#: 06:00–10:00, which is 09:00–12:00 and 14:00–18:00 in China — the working day
#: of the people this product is for.
PEAK_HOURS_UTC: frozenset[int] = frozenset({1, 2, 3, 6, 7, 8, 9})


def is_peak(moment: datetime) -> bool:
    """Whether DeepSeek was charging its peak rate at this moment."""
    return moment.weekday() < 5 and moment.hour in PEAK_HOURS_UTC


def rates_at(pricing: ModelPricing, moment: datetime | None) -> ModelRates:
    """The rates in force then — or peak, when nobody said when.

    Peak is the default because it is the pessimistic one. A cost that assumed
    the discount and did not get it understates what 立言阁 paid, and an
    understated cost is the kind of wrong that only shows up in the margin.
    """
    return pricing.peak if moment is None or is_peak(moment) else pricing.off_peak


#: Render `starter` at $7/month is $0.0000027 per second of wall clock.
WORKER_MICROS_PER_MILLION_MILLISECONDS = 2_700

#: R2 at $0.015/GB-month, held for the retention `credits.md` assumes.
STORAGE_MICROS_PER_MILLION_BYTES = 180

#: K from `credits.md`: what one dollar of 立言阁's own cost is worth in 额度.
#: It ties a credit to cost and does not move; margin lives in how much 额度 a
#: dollar buys, which is not this module's business.
CREDITS_PER_DOLLAR_OF_COST = 2_000

#: Flat, per 来源, whatever it turns out to be. A 250x difference in length makes
#: only a 4x difference in the infrastructure a 来源 costs, so this is charged
#: rather than computed — and the measured cost beside it is how anyone finds
#: out whether three is still the right number.
CAPTURE_CREDITS = 3


def _apply(units: int, micros_per_million: int) -> int:
    """One rate against one measurement, rounded to the nearest micro-dollar.

    Nearest rather than floored: these are summed over every run the product
    ever makes, and a floor would understate the total by half a micro-dollar
    every time, always in the same direction.
    """
    return (units * micros_per_million + PER_MILLION // 2) // PER_MILLION


def provider_cost_micros(
    usage: ProviderUsage,
    model: str,
    *,
    at: datetime | None = None,
) -> int | None:
    """What one 知言 or 立言 call cost, or nothing if the model has no rates.

    An unrated model returns `None` rather than guessing. A cost recorded as
    unknown is visible and countable; a cost quietly computed at another model's
    rates is neither, and would be believed.

    `at` is when the work happened. DeepSeek halves every rate outside its peak
    windows, and until this argument existed every run was recorded at peak —
    so a run at 03:00 China time was booked at twice what it cost, permanently
    and invisibly. Omitting `at` keeps the old pessimistic reading.
    """
    pricing = MODEL_RATES.get(model)
    if pricing is None:
        return None
    rates = rates_at(pricing, at)
    return (
        _apply(usage.uncached_input_tokens, rates.uncached_input)
        + _apply(usage.cached_input_tokens, rates.cached_input)
        + _apply(usage.output_tokens, rates.output)
    )


def worker_cost_micros(milliseconds: int) -> int:
    """What holding a worker for this long cost."""
    return _apply(max(0, milliseconds), WORKER_MICROS_PER_MILLION_MILLISECONDS)


def storage_cost_micros(stored_bytes: int) -> int:
    """What keeping this many bytes in R2 costs over the assumed retention."""
    return _apply(max(0, stored_bytes), STORAGE_MICROS_PER_MILLION_BYTES)


def credits_for(cost_micros: int) -> int:
    """What 立言阁 would charge for work that cost this much.

    Rounded up, and never to nothing: an act that consumed something real must
    not be free because it was cheap.
    """
    divisor = PER_MILLION // CREDITS_PER_DOLLAR_OF_COST
    return max(1, -(-max(0, cost_micros) // divisor))


# --- Estimating a run before it happens -------------------------------------
#
# A 预扣 is taken at what a run is expected to cost, and settled against what it
# did. These are the coefficients that expectation is built from. They live here
# rather than in settings because they are a model of the provider, not a knob
# per environment: every deployment should hold the same view of what a run
# costs, and a wrong one should be wrong in a place that is reviewed.
#
# None of them is fitted yet. `docs/operations/credits.md` says which are
# assumptions and which the afternoon of 2026-08-27 measured, and
# `scripts/calibrate_costs.py` is what replaces them with a line through real
# runs. Until then they are deliberately generous: over-holding costs a user a
# refusal they could have afforded, under-holding costs 立言阁 money it cannot
# get back, and ADR-0008 chooses the first.

#: Assumed. DeepSeek's own guidance for Chinese text.
TOKENS_PER_CHARACTER = 0.6

#: Assumed. The instructions and report schema every 知言 run carries.
ZHIYAN_PREAMBLE_TOKENS = 2_000

#: Measured, thinly. Every 知言 run whose usage was recorded carried far more
#: input than 立言阁 sent: 43,081 and 165,577 tokens against 来源 of 2,882 and
#: 3,394 characters, so search injected roughly 39,000 and 161,000. The runs of
#: 2026-08-27 carried 46,000–142,000. This is the low end of that, because the
#: sample is two rows and both are short 来源 — the case `credits.md` names as
#: the hard one. A corpus spread across lengths replaces it.
ZHIYAN_SEARCH_TOKENS = 45_000

#: How much of that injection the provider serves from its cache. Around 90% in
#: every run measured, and it is why the term above can grow threefold without
#: the estimate following: a cache hit costs a thirty-first of a miss.
#:
#: This is the one place the estimator does not assume everything is uncached,
#: and the exception is deliberate. Search injection is the largest term in a
#: short 来源's estimate and the most reliably cached, so pricing it at the miss
#: rate does not buy pessimism — it triples the 预扣 and refuses users work they
#: can comfortably afford, which is the failure ADR-0008 was balancing against.
ZHIYAN_SEARCH_CACHE_HIT_RATE = 0.9

#: Measured, thinly. 15,161 output tokens on 2026-08-27 of which 11,205 were
#: reasoning; 11,218 and 23,308 in the two runs since. The report itself is
#: around 4,000 — but reasoning is billed as output, so the number that costs
#: money is the whole of it, and it is three to six times the report.
ZHIYAN_OUTPUT_TOKENS = 17_000

#: 立言 has no tool access and so no injection term: what it sends and what comes
#: back is the whole of it. Assumed to reason as much as 知言 does.
LIYAN_OUTPUT_TOKENS = 15_000

#: Assumed. The 主题知言 instructions and six-section schema are a little shorter
#: than 知言's seven, and the difference is well inside what "assumed" means.
THEME_PREAMBLE_TOKENS = 2_000

#: Assumed, from 知言's measured range. A 主题知言 run searches for the same reason
#: and under the same provider cap, so it is priced the same way — the same
#: injection, mostly cached — until 主题 runs of its own have been measured.
THEME_SEARCH_TOKENS = ZHIYAN_SEARCH_TOKENS
THEME_SEARCH_CACHE_HIT_RATE = ZHIYAN_SEARCH_CACHE_HIT_RATE

#: Assumed. Six sections against 知言's seven, and no per-fact verdict prose, so
#: a little less than 知言 writes.
THEME_OUTPUT_TOKENS = 15_000

#: Assumed. 提炼主题 cannot search, and what it returns is three lines and three
#: sentences — so its whole cost is the 来源 it reads plus a very short answer.
#: The reasoning is what dominates it, not the output.
THEME_PROPOSAL_PREAMBLE_TOKENS = 1_000
THEME_PROPOSAL_OUTPUT_TOKENS = 2_000


def _input_tokens(characters: int) -> int:
    return int(max(0, characters) * TOKENS_PER_CHARACTER)


def _estimate(input_tokens: int, output_tokens: int, model: str) -> int:
    """What a run costing this much would be charged.

    Estimated as an entirely uncached call, which is the pessimistic reading:
    cache hits are a discount the provider may or may not give on the day, and a
    预扣 that assumed one would under-hold exactly when the provider changed its
    mind.
    """
    usage = ProviderUsage(
        input_tokens=input_tokens,
        cached_input_tokens=0,
        output_tokens=output_tokens,
        reasoning_tokens=0,
        total_tokens=input_tokens + output_tokens,
    )
    # Estimated at peak whatever the hour. A 预扣 taken at the off-peak rate on
    # a run that finishes after the window opens under-holds, and ADR-0008
    # chooses over-holding: the user is refused work they could afford, rather
    # than 立言阁 collecting a shortfall it cannot.
    cost = provider_cost_micros(usage, model)
    if cost is None:
        # An unrated model cannot be estimated any more than it can be costed.
        # One 额度 is not a guess at the price; it is the smallest hold that
        # still requires the user to have some.
        return 1
    return credits_for(cost)


def estimate_zhiyan_credits(*, source_characters: int, model: str) -> int:
    """What analyzing one 来源 is expected to cost.

    The 来源 is in hand, so its own contribution is counted rather than guessed.
    What is predicted is the preamble, whatever the provider injects when it
    searches, and how long the report comes out.

    The 来源 and preamble are priced as cache misses and the injection mostly as
    hits, which is what every measured run shows. Treating the injection as a
    miss would put four fifths of the estimate on the term least likely to be
    billed that way.
    """
    pricing = MODEL_RATES.get(model)
    if pricing is None:
        return 1
    cached = int(ZHIYAN_SEARCH_TOKENS * ZHIYAN_SEARCH_CACHE_HIT_RATE)
    usage = ProviderUsage(
        input_tokens=(
            _input_tokens(source_characters) + ZHIYAN_PREAMBLE_TOKENS + ZHIYAN_SEARCH_TOKENS
        ),
        cached_input_tokens=cached,
        output_tokens=ZHIYAN_OUTPUT_TOKENS,
        reasoning_tokens=0,
        total_tokens=0,
    )
    cost = provider_cost_micros(usage, model)
    return credits_for(cost) if cost is not None else 1


def estimate_theme_credits(*, theme_characters: int, source_characters: int, model: str) -> int:
    """What analysing one 主题 is expected to cost.

    Priced like a 知言 run and for the same reason: it is one searching call with
    one structured report at the end of it. What it reads is larger — the 主题 is
    a line, but the 来源 of the whole 任务版本 travel with it as the baseline
    `blind_spots` is measured against — so every 来源 is counted here, where 知言
    counts one.
    """
    pricing = MODEL_RATES.get(model)
    if pricing is None:
        return 1
    cached = int(THEME_SEARCH_TOKENS * THEME_SEARCH_CACHE_HIT_RATE)
    usage = ProviderUsage(
        input_tokens=(
            _input_tokens(theme_characters + source_characters)
            + THEME_PREAMBLE_TOKENS
            + THEME_SEARCH_TOKENS
        ),
        cached_input_tokens=cached,
        output_tokens=THEME_OUTPUT_TOKENS,
        reasoning_tokens=0,
        total_tokens=0,
    )
    cost = provider_cost_micros(usage, model)
    return credits_for(cost) if cost is not None else 1


def estimate_theme_proposal_credits(*, source_characters: int, model: str) -> int:
    """What one press of 提炼主题 is expected to cost.

    No search, so no injection term: the 来源 in hand and a short answer are the
    whole of it. That makes this the cheapest metered operation in the system,
    which is as it should be — it is a step a user takes before they have decided
    anything.
    """
    return _estimate(
        _input_tokens(source_characters) + THEME_PROPOSAL_PREAMBLE_TOKENS,
        THEME_PROPOSAL_OUTPUT_TOKENS,
        model,
    )


def estimate_liyan_credits(*, input_characters: int, model: str) -> int:
    """What generating one 立言文章 is expected to cost.

    Its input is entirely known — the 知言报告 and the 立言指令 are both already
    written — so only the article's own length is predicted.
    """
    return _estimate(_input_tokens(input_characters), LIYAN_OUTPUT_TOKENS, model)
