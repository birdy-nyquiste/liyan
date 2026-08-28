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
    rates = MODEL_RATES[MODEL].peak
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


# --- The two windows DeepSeek charges in -------------------------------------


def test_peak_is_the_chinese_working_day_and_nothing_else() -> None:
    """01:00–04:00 and 06:00–10:00 UTC on weekdays — 09:00–12:00 and 14:00–18:00
    in China. The gap at 04:00–06:00 is real, and so is the whole weekend."""
    from datetime import UTC, datetime

    from liyan_server.rate_card import is_peak

    def moment(day: int, hour: int) -> datetime:
        return datetime(2026, 8, day, hour, 30, tzinfo=UTC)

    friday, saturday = 28, 29
    assert is_peak(moment(friday, 1))
    assert is_peak(moment(friday, 3))
    assert is_peak(moment(friday, 9))
    assert not is_peak(moment(friday, 0))
    assert not is_peak(moment(friday, 4)), "the two-hour gap between the windows"
    assert not is_peak(moment(friday, 5))
    assert not is_peak(moment(friday, 10))
    assert not is_peak(moment(saturday, 3)), "no weekend is peak"


def test_an_off_peak_run_is_costed_at_half_and_not_at_peak() -> None:
    """Every run used to be recorded at peak. A run at 03:00 China time was
    therefore booked at twice what it cost, permanently and invisibly."""
    from datetime import UTC, datetime

    from liyan_server.rate_card import provider_cost_micros

    consumed = usage(20_000, 5_000, cached=10_000)
    at_peak = provider_cost_micros(consumed, MODEL, at=datetime(2026, 8, 28, 2, tzinfo=UTC))
    off_peak = provider_cost_micros(consumed, MODEL, at=datetime(2026, 8, 28, 22, tzinfo=UTC))

    assert at_peak is not None and off_peak is not None
    assert off_peak * 2 == at_peak
    assert provider_cost_micros(consumed, MODEL) == at_peak, "peak when nobody says when"


def test_an_unrated_model_is_still_unknown_in_either_window() -> None:
    from datetime import UTC, datetime

    from liyan_server.rate_card import provider_cost_micros

    assert provider_cost_micros(usage(1_000, 1_000), "deepseek-v9") is None
    assert (
        provider_cost_micros(
            usage(1_000, 1_000), "deepseek-v9", at=datetime(2026, 8, 28, 22, tzinfo=UTC)
        )
        is None
    )


def test_the_zhiyan_estimate_brackets_what_real_runs_actually_cost() -> None:
    """The 预扣 used to sit below every run it was estimating.

    Two 知言 runs on short 来源 have recorded usage. Their provider term comes to
    36 and 89 额度 — 37 and 90 as recorded, the extra one being the worker they
    held — while the estimator predicted 28 for both: under the cheaper one and
    a third of the dearer. It under-held on every observed run,
    in the same direction, which is the one way ADR-0008 says not to be wrong.

    The estimate should now land between them: above what a well-behaved run
    costs, below what a search-heavy one does. Two points is not a calibration
    and this is not asserting a fit — it is asserting that the estimator is no
    longer *systematically* under the only evidence available.
    """
    from liyan_server.rate_card import estimate_zhiyan_credits

    cheapest = credits_for(
        provider_cost_micros(usage(43_081, 11_218, cached=37_504), MODEL) or 0
    )
    dearest = credits_for(
        provider_cost_micros(usage(165_577, 23_308, cached=138_880), MODEL) or 0
    )
    assert (cheapest, dearest) == (36, 89), "the two measured runs, priced at peak"

    estimated = estimate_zhiyan_credits(source_characters=2_882, model=MODEL)

    assert cheapest < estimated < dearest


def test_an_unrated_model_still_estimates_the_smallest_possible_hold() -> None:
    """One 额度 is not a guess at the price; it is the smallest hold that still
    requires the user to have some."""
    from liyan_server.rate_card import estimate_zhiyan_credits

    assert estimate_zhiyan_credits(source_characters=2_000, model="deepseek-v9") == 1
