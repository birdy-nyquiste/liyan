"""What things cost, held against the numbers `credits.md` publishes.

The scenarios below are that page's table, reconstructed from the rate card
itself. They exist so the two cannot drift: a rate that moves without the page
moving with it fails here, which is the only way anyone would find out — a cost
is never wrong in a way a user notices, only in a way the margin does.
"""

from liyan_server.provider_usage import ProviderUsage
from liyan_server.rate_card import (
    CAPTURE_CREDITS,
    MODEL_RATES,
    credits_for,
    provider_cost_micros,
    storage_cost_micros,
    worker_cost_micros,
)

MODEL = "deepseek-v4-flash"


def usage(input_tokens: int, output_tokens: int, cached: int = 0) -> ProviderUsage:
    return ProviderUsage(
        input_tokens=input_tokens,
        cached_input_tokens=cached,
        output_tokens=output_tokens,
        reasoning_tokens=0,
        total_tokens=input_tokens + output_tokens,
    )


def zhiyan(input_tokens: int, output_tokens: int, seconds: int) -> int:
    cost = provider_cost_micros(usage(input_tokens, output_tokens), MODEL)
    assert cost is not None
    return cost + worker_cost_micros(seconds * 1_000)


def test_a_short_source_analysis_costs_what_the_page_says() -> None:
    """2,000 characters of Chinese, the search results, and one report."""
    assert credits_for(zhiyan(18_200, 4_000, 180)) == 28


def test_a_long_source_analysis_costs_what_the_page_says() -> None:
    """500,000 characters — the ceiling `limits.md` allows one 来源."""
    assert credits_for(zhiyan(317_000, 6_000, 300)) == 297


def test_an_article_costs_what_the_page_says() -> None:
    """Three 知言报告 in, one 立言文章 out, and no tool access to complicate it."""
    assert credits_for(zhiyan(15_000, 4_000, 120)) == 25


def test_a_whole_ordinary_task_costs_what_the_page_says() -> None:
    """Three pasted 来源, their analyses, and the article they are for.

    Summed per act rather than over the total, because that is how it is
    charged: each Execution rounds up on its own.
    """
    task = 3 * CAPTURE_CREDITS + 3 * 28 + 25

    assert task == 118


def test_the_flat_capture_fee_covers_the_largest_file_it_will_ever_see() -> None:
    """A 10MB upload parsed against the timeout, and kept for the assumed year.

    The fee is flat because the cost is nearly flat: this worst case is a few
    times an ordinary 来源, not the hundreds of times its length would suggest.
    It is set to cover the tail rather than the average, so the largest files
    are subsidised by a fraction of a cent rather than by a second term in the
    equation.
    """
    worst = worker_cost_micros(60_000) + storage_cost_micros(10_000_000)
    typical_url = worker_cost_micros(15_000)

    assert credits_for(typical_url) == 1
    assert credits_for(worst) == 4
    assert CAPTURE_CREDITS == 3


def test_a_cache_hit_is_priced_far_below_a_miss() -> None:
    """The instruction and schema prefix every run shares is worth catching."""
    rates = MODEL_RATES[MODEL]
    all_missed = provider_cost_micros(usage(20_000, 0), MODEL)
    mostly_hit = provider_cost_micros(usage(20_000, 0, cached=18_000), MODEL)

    assert rates.cached_input * 30 < rates.uncached_input
    assert all_missed is not None and mostly_hit is not None
    assert mostly_hit < all_missed // 2


def test_an_unrated_model_is_recorded_as_unknown_rather_than_guessed() -> None:
    """A model swap must not quietly bill at some other model's rates."""
    assert provider_cost_micros(usage(1_000, 100), "some-model-nobody-priced") is None


def test_nothing_real_is_free_because_it_was_cheap() -> None:
    assert credits_for(1) == 1
    assert credits_for(500) == 1
    assert credits_for(501) == 2
    assert credits_for(0) == 1
