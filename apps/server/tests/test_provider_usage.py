"""What the meter reads, and what it does when the provider says nothing.

Every 额度 charged for 知言 or 立言 starts here, so the two counts that decide a
cost — how much input missed the cache, and how much output came back — are
worth pinning down separately from any adapter that uses them.
"""

from liyan_server.provider_usage import ProviderUsage, provider_usage


def a_payload(usage: object) -> dict[str, object]:
    return {"id": "resp_1", "status": "completed", "output": [], "usage": usage}


def test_a_full_usage_block_is_read_as_the_provider_states_it() -> None:
    usage = provider_usage(
        a_payload(
            {
                "input_tokens": 18_200,
                "input_tokens_details": {"cached_tokens": 2_000},
                "output_tokens": 4_000,
                "output_tokens_details": {"reasoning_tokens": 900},
                "total_tokens": 22_200,
            }
        )
    )

    assert usage == ProviderUsage(
        input_tokens=18_200,
        cached_input_tokens=2_000,
        output_tokens=4_000,
        reasoning_tokens=900,
        total_tokens=22_200,
    )


def test_cached_input_is_taken_out_of_what_is_billed_at_the_full_rate() -> None:
    """DeepSeek reports the cache hit inside the input total, not beside it.

    A cache hit costs a small fraction of a miss, so reading `input_tokens` as
    though all of it missed would overstate every cost by the size of the
    prompt prefix every run shares.
    """
    usage = provider_usage(
        a_payload(
            {
                "input_tokens": 18_200,
                "input_tokens_details": {"cached_tokens": 2_000},
                "output_tokens": 4_000,
            }
        )
    )

    assert usage is not None
    assert usage.uncached_input_tokens == 16_200


def test_a_response_that_reports_nothing_is_not_a_failure() -> None:
    """A 知言报告 must never be lost over an accounting field.

    The cost of this is a record with no tokens on it, which is visible and
    countable. The cost of the alternative is real work thrown away.
    """
    assert provider_usage(a_payload(None)) is None
    assert provider_usage({"id": "resp_1"}) is None
    assert provider_usage("not a payload") is None


def test_a_usage_missing_either_required_count_cannot_be_costed() -> None:
    assert provider_usage(a_payload({"input_tokens": 100})) is None
    assert provider_usage(a_payload({"output_tokens": 100})) is None


def test_an_absent_breakdown_means_none_of_it_rather_than_unknown() -> None:
    """No cache-hit detail and no cache hits are the same thing for a cost."""
    usage = provider_usage(a_payload({"input_tokens": 300, "output_tokens": 50}))

    assert usage is not None
    assert usage.cached_input_tokens == 0
    assert usage.reasoning_tokens == 0
    assert usage.uncached_input_tokens == 300


def test_a_missing_total_is_filled_in_rather_than_refused() -> None:
    usage = provider_usage(a_payload({"input_tokens": 300, "output_tokens": 50}))

    assert usage is not None
    assert usage.total_tokens == 350


def test_a_boolean_is_not_a_token_count() -> None:
    """`True` is an `int` in Python, and would otherwise be billed as one token."""
    assert provider_usage(a_payload({"input_tokens": True, "output_tokens": 50})) is None

    usage = provider_usage(
        a_payload(
            {
                "input_tokens": 300,
                "input_tokens_details": {"cached_tokens": True},
                "output_tokens": 50,
            }
        )
    )

    assert usage is not None
    assert usage.cached_input_tokens == 0
