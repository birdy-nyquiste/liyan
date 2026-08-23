from datetime import UTC, datetime, timedelta

from liyan_server.zhiyan.recovery import (
    MANUAL_RETRY_WINDOW,
    automatic_attempt_permitted,
    is_recoverable,
    retry_allowed_at,
    retry_state,
)

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def test_only_the_initial_run_recovers_on_its_own_and_only_once() -> None:
    assert automatic_attempt_permitted(
        origin="initial", attempt=1, failure_code="provider_unavailable"
    )
    assert not automatic_attempt_permitted(
        origin="initial", attempt=2, failure_code="provider_unavailable"
    )
    assert not automatic_attempt_permitted(
        origin="automatic", attempt=2, failure_code="provider_unavailable"
    )
    assert not automatic_attempt_permitted(
        origin="manual", attempt=3, failure_code="provider_unavailable"
    )


def test_a_failure_another_run_cannot_survive_never_spends_the_automatic_attempt() -> None:
    assert not is_recoverable("provider_unconfigured")
    assert not is_recoverable("invalid_run_snapshot")
    assert not is_recoverable("dispatch_failed")
    assert not automatic_attempt_permitted(
        origin="initial", attempt=1, failure_code="provider_unconfigured"
    )


def test_a_rejected_report_is_worth_one_more_run() -> None:
    assert is_recoverable("unsupported_fact_verdict")
    assert automatic_attempt_permitted(
        origin="initial", attempt=1, failure_code="unsupported_fact_verdict"
    )


def test_the_server_backs_a_rate_limited_provider_off_the_longest() -> None:
    rate_limited = retry_allowed_at(NOW, "provider_rate_limited")
    unavailable = retry_allowed_at(NOW, "provider_unavailable")
    rejected = retry_allowed_at(NOW, "unsupported_fact_verdict")

    assert NOW < rejected < unavailable < rate_limited
    assert retry_allowed_at(NOW, "provider_unconfigured") == NOW


def test_a_target_with_no_history_may_retry_immediately() -> None:
    state = retry_state(now=NOW, manual_run_times=[], earliest_retry_at=None)

    assert state == retry_state(now=NOW, manual_run_times=[], earliest_retry_at=None)
    assert state.allowed is True
    assert state.remaining == 2
    assert state.allowed_at is None


def test_a_pending_backoff_withholds_the_retry_and_names_its_moment() -> None:
    release = NOW + timedelta(seconds=30)

    state = retry_state(now=NOW, manual_run_times=[], earliest_retry_at=release)

    assert state.allowed is False
    assert state.allowed_at == release
    assert state.remaining == 2


def test_an_elapsed_backoff_stops_being_reported() -> None:
    state = retry_state(
        now=NOW,
        manual_run_times=[],
        earliest_retry_at=NOW - timedelta(seconds=1),
    )

    assert state.allowed is True
    assert state.allowed_at is None


def test_two_manual_retries_exhaust_the_rolling_window() -> None:
    first = NOW - timedelta(minutes=10)
    second = NOW - timedelta(minutes=4)

    state = retry_state(now=NOW, manual_run_times=[first, second], earliest_retry_at=None)

    assert state.allowed is False
    assert state.remaining == 0
    assert state.allowed_at == first + MANUAL_RETRY_WINDOW


def test_manual_retries_older_than_the_window_no_longer_count() -> None:
    state = retry_state(
        now=NOW,
        manual_run_times=[
            NOW - MANUAL_RETRY_WINDOW - timedelta(seconds=1),
            NOW - timedelta(minutes=5),
        ],
        earliest_retry_at=None,
    )

    assert state.allowed is True
    assert state.remaining == 1


def test_the_later_of_backoff_and_window_release_wins() -> None:
    exhausting = [NOW - timedelta(minutes=29), NOW - timedelta(minutes=28)]

    beyond_window = retry_state(
        now=NOW,
        manual_run_times=exhausting,
        earliest_retry_at=NOW + timedelta(hours=1),
    )
    inside_window = retry_state(
        now=NOW,
        manual_run_times=exhausting,
        earliest_retry_at=NOW + timedelta(seconds=15),
    )

    assert beyond_window.allowed_at == NOW + timedelta(hours=1)
    assert inside_window.allowed_at == exhausting[0] + MANUAL_RETRY_WINDOW
