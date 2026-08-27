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
