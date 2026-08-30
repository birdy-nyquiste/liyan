"""What an 额度包 configuration may be, and what fails the boot instead.

`app.py` reads this at startup for the same reason it reads 发布目标 there: an
operator should learn about a malformed pack from a server that will not start,
not from the first user who clicks 购买.
"""

import pytest

from liyan_server.billing.packs import (
    CreditPacksMisconfigured,
    billing_state,
    configured_packs,
    pack_for,
)
from liyan_server.settings import Settings


def settings_with(packs: str, **overrides: object) -> Settings:
    """Settings that say only what a test said, and nothing from a local `.env`.

    `Settings` reads `.env`, so a developer with real Stripe keys would give
    every one of these tests a secret key it never asked for — and the test
    below about the dangerous half-configuration would pass for the wrong
    reason, or fail for one.
    """
    return Settings(
        **{
            "database_url": "sqlite+pysqlite:///:memory:",
            "stripe_credit_packs": packs,
            "stripe_secret_key": "",
            "stripe_webhook_secret": "",
            **overrides,
        }  # type: ignore[arg-type]
    )


def test_packs_keep_the_order_an_operator_wrote_them_in() -> None:
    """That order is the order the workbench shows them in, so the cheapest way
    in stays first without the client sorting on a number it should not read."""
    settings = settings_with(
        '[{"price_id": "price_c", "credits": 20000},'
        ' {"price_id": "price_a", "credits": 2000},'
        ' {"price_id": "price_b", "credits": 8000}]'
    )

    assert [pack.price_id for pack in configured_packs(settings)] == [
        "price_c",
        "price_a",
        "price_b",
    ]


def test_a_price_that_is_not_on_offer_is_worth_nothing() -> None:
    """Not a default, and not an error either. A retired 额度包 and another
    product's Price both land here, and both must refuse to credit."""
    settings = settings_with('[{"price_id": "price_a", "credits": 2000}]')

    assert pack_for(settings, "price_a") is not None
    assert pack_for(settings, "price_retired") is None


def test_selling_nothing_is_a_configuration_rather_than_a_fault() -> None:
    assert configured_packs(settings_with("")) == ()
    assert billing_state(settings_with("")) == "unconfigured"


@pytest.mark.parametrize(
    "packs",
    [
        "{not json",
        '{"price_id": "price_a", "credits": 2000}',
        "[[]]",
        '[{"credits": 2000}]',
        '[{"price_id": "", "credits": 2000}]',
        '[{"price_id": "price_a"}]',
        '[{"price_id": "price_a", "credits": 0}]',
        '[{"price_id": "price_a", "credits": -5}]',
        '[{"price_id": "price_a", "credits": "2000"}]',
        '[{"price_id": "price_a", "credits": 2000}, {"price_id": "price_a", "credits": 8000}]',
    ],
    ids=[
        "not json",
        "not an array",
        "not an object",
        "no price",
        "empty price",
        "no credits",
        "zero credits",
        "negative credits",
        "credits as a string",
        "the same price twice",
    ],
)
def test_configuration_nobody_could_act_on_refuses_to_start(packs: str) -> None:
    """A pack worth nothing took somebody's money for no 额度, and a price
    configured twice means two answers to what one payment bought. Both are
    worth refusing to start over."""
    with pytest.raises(CreditPacksMisconfigured):
        configured_packs(settings_with(packs))


def test_a_secret_key_without_a_signing_secret_is_not_configured() -> None:
    """The dangerous half: Checkout would open and nothing would ever credit."""
    packs = '[{"price_id": "price_a", "credits": 2000}]'

    assert billing_state(settings_with(packs, stripe_secret_key="sk_test_x")) == "unconfigured"
    assert (
        billing_state(
            settings_with(
                packs,
                stripe_secret_key="sk_test_x",
                stripe_webhook_secret="whsec_x",
            )
        )
        == "configured"
    )
