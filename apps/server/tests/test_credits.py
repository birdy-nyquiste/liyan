"""What a user's 额度 come to, through every movement that changes them.

The balance is a sum over rows, so the thing worth testing is not arithmetic but
what happens when a movement is made twice: a worker that retries, a Stripe
webhook redelivered, an intake replayed. Each of those is a way of giving
somebody 额度 they did not buy, or taking ones they did.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from database_support import migrated_database
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from liyan_server import credits
from liyan_server.database import CreditEntry, Database, User

REVISION = "source_revision"
NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def a_user(tmp_path: Path) -> tuple[Database, User]:
    database = Database(migrated_database(tmp_path))
    assert database.engine is not None
    with Session(database.engine) as session:
        user = User(auth_subject="subject-1", email="writer@example.com")
        session.add(user)
        session.commit()
        session.refresh(user)
    return database, user


def test_a_new_ledger_is_empty_rather_than_absent(tmp_path: Path) -> None:
    database, user = a_user(tmp_path)
    assert database.engine is not None
    with Session(database.engine) as session:
        assert credits.remaining(session, user.id) == 0
        assert credits.has_purchased(session, user.id) is False


def test_a_run_that_cost_less_than_expected_gives_the_difference_back(tmp_path: Path) -> None:
    database, user = a_user(tmp_path)
    assert database.engine is not None
    target = uuid4()
    with Session(database.engine) as session:
        credits.grant(session, user.id, 8_000, now=NOW)
        credits.hold(
            session, user.id, target_type=REVISION, target_id=target, attempt=1, credits=30, now=NOW
        )
        assert credits.remaining(session, user.id) == 7_970

        credits.settle(
            session, user.id, target_type=REVISION, target_id=target, attempt=1, actual=26, now=NOW
        )

        assert credits.remaining(session, user.id) == 7_974


def test_a_run_that_produced_nothing_costs_nothing(tmp_path: Path) -> None:
    """The whole 预扣 comes back. A user never pays for a run that gave them
    nothing, which is only affordable because the estimate bounds the loss."""
    database, user = a_user(tmp_path)
    assert database.engine is not None
    target = uuid4()
    with Session(database.engine) as session:
        credits.grant(session, user.id, 100, now=NOW)
        credits.hold(
            session, user.id, target_type=REVISION, target_id=target, attempt=1, credits=30, now=NOW
        )
        credits.settle(
            session, user.id, target_type=REVISION, target_id=target, attempt=1, actual=0, now=NOW
        )

        assert credits.remaining(session, user.id) == 100


def test_a_run_that_overshot_its_estimate_collects_the_shortfall(tmp_path: Path) -> None:
    """立言阁 does not absorb its own modelling error as a matter of course.
    The charge is what the work cost, not what was guessed."""
    database, user = a_user(tmp_path)
    assert database.engine is not None
    target = uuid4()
    with Session(database.engine) as session:
        credits.grant(session, user.id, 100, now=NOW)
        credits.hold(
            session, user.id, target_type=REVISION, target_id=target, attempt=1, credits=30, now=NOW
        )
        credits.settle(
            session, user.id, target_type=REVISION, target_id=target, attempt=1, actual=41, now=NOW
        )

        assert credits.remaining(session, user.id) == 59


def test_settling_twice_does_not_pay_twice(tmp_path: Path) -> None:
    """The worker writes this eagerly so the number moves while a user watches,
    and the reconciling sweep writes it for the paths nobody remembered. Both
    running is the normal case, not the exception."""
    database, user = a_user(tmp_path)
    assert database.engine is not None
    target = uuid4()
    with Session(database.engine) as session:
        credits.grant(session, user.id, 100, now=NOW)
        credits.hold(
            session, user.id, target_type=REVISION, target_id=target, attempt=1, credits=30, now=NOW
        )
        first = credits.settle(
            session, user.id, target_type=REVISION, target_id=target, attempt=1, actual=26, now=NOW
        )
        second = credits.settle(
            session,
            user.id,
            target_type=REVISION,
            target_id=target,
            attempt=1,
            actual=26,
            now=NOW + timedelta(minutes=5),
        )

        assert first is not None and second is None
        assert credits.remaining(session, user.id) == 74


def test_a_retry_holds_again_after_the_failed_attempt_gave_its_credits_back(
    tmp_path: Path,
) -> None:
    """One 预扣 per attempt, not per target. A failed run settles to zero and a
    manual retry is a fresh attempt, so the user pays once for one report."""
    database, user = a_user(tmp_path)
    assert database.engine is not None
    target = uuid4()
    with Session(database.engine) as session:
        credits.grant(session, user.id, 100, now=NOW)
        credits.hold(
            session, user.id, target_type=REVISION, target_id=target, attempt=1, credits=30, now=NOW
        )
        credits.settle(
            session, user.id, target_type=REVISION, target_id=target, attempt=1, actual=0, now=NOW
        )
        credits.hold(
            session, user.id, target_type=REVISION, target_id=target, attempt=2, credits=30, now=NOW
        )
        credits.settle(
            session, user.id, target_type=REVISION, target_id=target, attempt=2, actual=28, now=NOW
        )

        assert credits.remaining(session, user.id) == 72


def test_settling_work_that_was_never_held_writes_nothing(tmp_path: Path) -> None:
    database, user = a_user(tmp_path)
    assert database.engine is not None
    with Session(database.engine) as session:
        credits.grant(session, user.id, 100, now=NOW)

        assert (
            credits.settle(
                session,
                user.id,
                target_type=REVISION,
                target_id=uuid4(),
                attempt=1,
                actual=26,
                now=NOW,
            )
            is None
        )
        assert credits.remaining(session, user.id) == 100


def test_a_replayed_intake_charges_one_capture(tmp_path: Path) -> None:
    database, user = a_user(tmp_path)
    assert database.engine is not None
    preparation = uuid4()
    with Session(database.engine) as session:
        credits.grant(session, user.id, 100, now=NOW)
        first = credits.charge_capture(
            session, user.id, preparation_id=preparation, credits=3, now=NOW
        )
        second = credits.charge_capture(
            session, user.id, preparation_id=preparation, credits=3, now=NOW
        )

        assert first is not None and second is None
        assert credits.remaining(session, user.id) == 97


def test_a_redelivered_stripe_event_credits_once(tmp_path: Path) -> None:
    """Stripe retries webhooks, and one payment can arrive as two events.
    Fulfilling either twice is the most expensive mistake available here, so the
    payment is the key rather than the delivery."""
    database, user = a_user(tmp_path)
    assert database.engine is not None
    with Session(database.engine) as session:
        first = credits.purchase(session, user.id, 8_000, stripe_reference="pi_1", now=NOW)
        second = credits.purchase(session, user.id, 8_000, stripe_reference="pi_1", now=NOW)

        assert first is not None and second is None
        assert credits.remaining(session, user.id) == 8_000
        assert credits.has_purchased(session, user.id) is True


def test_a_dispute_may_take_a_balance_below_zero(tmp_path: Path) -> None:
    """The one movement allowed to. What is left is a debt rather than a spend,
    and hiding it at zero would let the same person start again for free."""
    database, user = a_user(tmp_path)
    assert database.engine is not None
    with Session(database.engine) as session:
        credits.purchase(session, user.id, 8_000, stripe_reference="pi_1", now=NOW)
        credits.hold(
            session,
            user.id,
            target_type=REVISION,
            target_id=uuid4(),
            attempt=1,
            credits=2_000,
            now=NOW,
        )
        credits.clawback(session, user.id, 8_000, stripe_reference="pi_1#dispute:du_1", now=NOW)

        assert credits.remaining(session, user.id) == -2_000


def test_the_database_refuses_a_second_hold_even_if_the_check_is_skipped(
    tmp_path: Path,
) -> None:
    """The functions check first so the common case is not an exception, but the
    index is what actually enforces it — two workers racing do not take turns."""
    database, user = a_user(tmp_path)
    assert database.engine is not None
    target = uuid4()
    with Session(database.engine) as session:
        credits.hold(
            session, user.id, target_type=REVISION, target_id=target, attempt=1, credits=30, now=NOW
        )
        session.add(
            CreditEntry(
                owner_id=user.id,
                kind="hold",
                amount=-30,
                target_type=REVISION,
                target_id=target,
                attempt=1,
                created_at=NOW,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
