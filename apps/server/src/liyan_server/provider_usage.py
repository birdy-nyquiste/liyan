"""What one provider call reports having consumed.

Every 额度 charged for 知言 or 立言 is derived from this block, so it is read in
one place rather than in each adapter. Two copies of "what DeepSeek says it
used" would be two things to keep true, and the one that drifted would be
invisible: a cost is never wrong in a way anybody notices until the margin is.

Absence is not a failure. A run that produced a 知言报告 has done its job, and a
missing or oddly shaped `usage` must never be the reason a user loses it — the
same judgement `record_heartbeat` makes about a heartbeat it could not write.
The price of that is a cost record with no tokens on it, which is visible in the
data and can be counted; the price of the alternative is throwing away real work
over an accounting field.
"""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderUsage:
    """Tokens one provider call reports, as DeepSeek's Responses API states them."""

    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    total_tokens: int

    @property
    def uncached_input_tokens(self) -> int:
        """Input billed at the full rate, rather than at the cache-hit rate.

        DeepSeek prices a cache hit at a small fraction of a miss and reports
        the two together — `input_tokens` includes `cached_tokens` rather than
        excluding them — so it is the split, never the total, that a cost is
        computed from.
        """
        return max(0, self.input_tokens - self.cached_input_tokens)


def _whole(value: object) -> int | None:
    """An integer the provider actually sent, or nothing.

    `bool` is excluded deliberately: it is an `int` in Python, and a `True` that
    reached a token count would be silently billed as one token.
    """
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _detail(block: dict[str, object], key: str, field: str) -> int:
    """One nested count, treating an absent details object as zero.

    A response that reports no cache hits and one that omits the breakdown are
    the same thing for a cost: nothing was cached.
    """
    details = block.get(key)
    if not isinstance(details, dict):
        return 0
    return _whole(details.get(field)) or 0


def provider_usage(payload: object) -> ProviderUsage | None:
    """Read the `usage` block from a Responses API payload, if it carries one.

    Only the two required counts decide whether there is a usage at all. The
    breakdowns are optional in the API and are treated as zero when absent,
    which is also what they mean.
    """
    if not isinstance(payload, dict):
        return None
    block = payload.get("usage")
    if not isinstance(block, dict):
        return None
    input_tokens = _whole(block.get("input_tokens"))
    output_tokens = _whole(block.get("output_tokens"))
    if input_tokens is None or output_tokens is None:
        return None
    return ProviderUsage(
        input_tokens=input_tokens,
        cached_input_tokens=_detail(block, "input_tokens_details", "cached_tokens"),
        output_tokens=output_tokens,
        reasoning_tokens=_detail(block, "output_tokens_details", "reasoning_tokens"),
        total_tokens=_whole(block.get("total_tokens")) or input_tokens + output_tokens,
    )


def combined_usage(usages: Sequence[ProviderUsage | None]) -> ProviderUsage | None:
    """What a run consumed when it took more than one call to get an answer.

    A 知言 run is one provider call until the provider stops mid-search and has
    to be asked again (`zhiyan/deepseek`). Each of those calls is invoiced on
    its own, so what the run cost is their sum — and reading only the last one
    would report the cheapest call of a run whose whole expense was the earlier
    ones.

    `None` entries are calls that reported nothing, and they are skipped rather
    than counted as zero: a run where one call in three came back without a
    meter has an understated cost, not a wrong one, and the alternative is
    discarding the two that did report.
    """
    present = [usage for usage in usages if usage is not None]
    if not present:
        return None
    return ProviderUsage(
        input_tokens=sum(usage.input_tokens for usage in present),
        cached_input_tokens=sum(usage.cached_input_tokens for usage in present),
        output_tokens=sum(usage.output_tokens for usage in present),
        reasoning_tokens=sum(usage.reasoning_tokens for usage in present),
        total_tokens=sum(usage.total_tokens for usage in present),
    )
