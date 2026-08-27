"""What 立言阁's suppliers charge, and what that comes to in 额度.

Every rate here is micros of one US dollar per *million* units of whatever it
measures — tokens, milliseconds of worker time, bytes retained. One divisor
serves all of them, and nothing needs a float: money in this system is integer
micro-dollars from the provider's invoice to the user's balance.

`docs/operations/credits.md` is where these numbers come from, why they are the
peak rather than the off-peak ones, and what a credit is worth. This module is
only their application.

`RATE_CARD_VERSION` is stamped onto every cost record so a charge stays
explainable after a rate moves. ADR-0009 governs how one may move: a change may
lower an operation's 额度 cost and never raise it, because 额度 already bought
are a promise about how much work they will do.
"""

from dataclasses import dataclass

from liyan_server.provider_usage import ProviderUsage

#: Bump on any change to the numbers below, so historical costs stay readable.
RATE_CARD_VERSION = 1

#: Every rate is quoted per this many units.
PER_MILLION = 1_000_000


@dataclass(frozen=True)
class ModelRates:
    """Micro-dollars per million tokens, at peak.

    Peak because peak is when this product is used: DeepSeek's peak window is
    01:00–04:00 and 06:00–10:00 UTC on weekdays, which is the Chinese working
    day. Costing at the off-peak rate would halve the apparent price of the
    hours the work actually happens in.
    """

    uncached_input: int
    cached_input: int
    output: int


MODEL_RATES: dict[str, ModelRates] = {
    "deepseek-v4-flash": ModelRates(
        uncached_input=440_000,
        cached_input=14_000,
        output=1_320_000,
    ),
    "deepseek-v4-pro": ModelRates(
        uncached_input=1_320_000,
        cached_input=44_000,
        output=3_960_000,
    ),
}

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


def provider_cost_micros(usage: ProviderUsage, model: str) -> int | None:
    """What one 知言 or 立言 call cost, or nothing if the model has no rates.

    An unrated model returns `None` rather than guessing. A cost recorded as
    unknown is visible and countable; a cost quietly computed at another model's
    rates is neither, and would be believed.
    """
    rates = MODEL_RATES.get(model)
    if rates is None:
        return None
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

#: Assumed, and known to be low. Runs measured on 2026-08-27 carried 46,000 to
#: 142,000 input tokens — but around 90% were cache hits at a thirty-first of
#: the price, so the figure that matters for a cost is much smaller than the one
#: that matters for a context window.
ZHIYAN_SEARCH_TOKENS = 15_000

#: Measured once, on 2026-08-27: 15,161 output tokens, of which 11,205 were
#: reasoning. The report itself was 3,956 — but reasoning is billed as output,
#: so the number that costs money is the whole of it.
ZHIYAN_OUTPUT_TOKENS = 15_000

#: 立言 has no tool access and so no injection term: what it sends and what comes
#: back is the whole of it. Assumed to reason as much as 知言 does.
LIYAN_OUTPUT_TOKENS = 15_000


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
    """
    return _estimate(
        _input_tokens(source_characters) + ZHIYAN_PREAMBLE_TOKENS + ZHIYAN_SEARCH_TOKENS,
        ZHIYAN_OUTPUT_TOKENS,
        model,
    )


def estimate_liyan_credits(*, input_characters: int, model: str) -> int:
    """What generating one 立言文章 is expected to cost.

    Its input is entirely known — the 知言报告 and the 立言指令 are both already
    written — so only the article's own length is predicted.
    """
    return _estimate(_input_tokens(input_characters), LIYAN_OUTPUT_TOKENS, model)
