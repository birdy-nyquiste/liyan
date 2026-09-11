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

#: 立言 only. It never searches, so the web_search change did not reach it.
MODEL = "deepseek-v4-flash"

#: 知言, 主题知言 and 提炼主题. flash stopped executing web search, and a 知言 run
#: that cannot search is refused rather than priced (ADR-0004).
ZHIYAN_MODEL = "deepseek-v4-pro"


def usage(input_tokens: int, output_tokens: int, cached: int = 0) -> ProviderUsage:
    return ProviderUsage(
        input_tokens=input_tokens,
        cached_input_tokens=cached,
        output_tokens=output_tokens,
        reasoning_tokens=0,
        total_tokens=input_tokens + output_tokens,
    )


def run(
    input_tokens: int,
    output_tokens: int,
    seconds: int,
    *,
    model: str,
    cached: int = 0,
) -> int:
    """One operation's provider bill plus the worker it held.

    `model` has no default on purpose. Every scenario below names the model it
    runs on, because the alternative let this file go on passing while the page
    it guards went stale: when 知言 moved from flash to pro, these assertions
    kept asserting flash's arithmetic — correctly, and about an operation that
    no longer existed.
    """
    cost = provider_cost_micros(usage(input_tokens, output_tokens, cached=cached), model)
    assert cost is not None
    return cost + worker_cost_micros(seconds * 1_000)


def test_a_short_source_analysis_costs_what_the_page_says() -> None:
    """A short 来源 whose run searched about as much as they usually do."""
    assert credits_for(run(88_000, 7_500, 114, model=ZHIYAN_MODEL, cached=80_000)) == 89


def test_a_search_heavy_analysis_costs_what_the_page_says() -> None:
    """The dearest injection recorded — 564k tokens, against a 56-character 来源.

    Not a long 来源: what a 知言 run reads depends on what it finds, so the
    expensive case is a hard question rather than a long one.
    """
    assert credits_for(run(565_766, 12_000, 300, model=ZHIYAN_MODEL, cached=543_616)) == 203


def test_extracting_themes_costs_what_the_page_says() -> None:
    """提炼主题 cannot search, and pays pro's rates anyway — it shares 知言's
    setting. The page says so rather than the code hiding it."""
    assert credits_for(run(6_000, 2_000, 40, model=ZHIYAN_MODEL)) == 32


def test_a_theme_analysis_costs_what_the_page_says() -> None:
    """主题知言 searches like 知言 and reads every 来源 of the 任务版本."""
    assert credits_for(run(120_000, 9_000, 140, model=ZHIYAN_MODEL, cached=108_000)) == 114


def test_an_article_costs_what_the_page_says() -> None:
    """Three 知言报告 in, one 立言文章 out, and no tool access to complicate it.

    Still flash, and the only operation that still is: 立言 never searches, so
    nothing about the web_search change reached it.
    """
    assert credits_for(run(15_000, 4_000, 120, model=MODEL)) == 25


def test_a_whole_ordinary_task_costs_what_the_page_says() -> None:
    """Three pasted 来源, their analyses, and the article they are for.

    Summed per act rather than over the total, because that is how it is
    charged: each Execution rounds up on its own.
    """
    task = 3 * CAPTURE_CREDITS + 3 * 89 + 25

    assert task == 301
    assert task + 32 + 114 == 447, "the same task with one press of 提炼主题 and a 主题报告"
    assert 3 * CAPTURE_CREDITS + 3 * 203 + 25 == 643, "when every run searches hard"


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


def test_the_zhiyan_estimate_covers_what_real_runs_actually_cost() -> None:
    """The 预扣 must sit at or above the runs it is estimating.

    Four `deepseek-v4-pro` runs at `effort: "low"` on 2026-09-11 — what a 知言
    run now is — settle at 76, 83, 90 and 105 额度. Under-holding is the one way
    ADR-0008 says not to be wrong, and it is the expensive way, because the
    shortfall is money 立言阁 cannot go back for.

    Covering rather than bracketing is the change the model brought. Against
    flash this test asserted the estimate landed *between* the cheapest and
    dearest observed run, which was a reasonable reading when the spread was
    43k–166k injected tokens. Pro's injection has been seen from 44k to 564k, a
    thirteenfold spread, so an estimate sitting inside that range is an estimate
    that under-holds whenever a run searches hard.

    So the bar is the tail rather than the sample: the hold must cover the
    dearest injection anyone has recorded, not merely the runs that happened to
    be measured last. This asserts no fit — only that nothing yet observed would
    have escaped the hold.
    """
    from liyan_server.rate_card import estimate_zhiyan_credits

    settled = [
        credits_for(provider_cost_micros(u, ZHIYAN_MODEL) or 0)
        for u in (
            usage(76_897, 6_415, cached=70_016),
            usage(43_796, 9_511, cached=39_808),
            usage(81_558, 6_932, cached=73_728),
            usage(152_871, 7_093, cached=139_392),
        )
    ]
    assert settled == [76, 90, 83, 105], "the four measured runs, priced at peak"

    # The dearest injection anyone has seen — 564k tokens — repriced at what a
    # `low` run writes. It is the case the hold exists for, and it is far above
    # anything the four runs above reached.
    heaviest = usage(565_766, 7_000, cached=543_616)
    tail = credits_for(provider_cost_micros(heaviest, ZHIYAN_MODEL) or 0)
    assert tail == 162

    estimated = estimate_zhiyan_credits(source_characters=2_882, model=ZHIYAN_MODEL)

    assert estimated >= tail, "a hold under the dearest run anyone has seen is a shortfall"
    assert estimated < 2 * tail, "and one far over it refuses work users can afford"


def test_an_unrated_model_still_estimates_the_smallest_possible_hold() -> None:
    """One 额度 is not a guess at the price; it is the smallest hold that still
    requires the user to have some."""
    from liyan_server.rate_card import estimate_zhiyan_credits

    assert estimate_zhiyan_credits(source_characters=2_000, model="deepseek-v9") == 1
