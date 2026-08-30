"""A real Stripe round-trip, run only when explicitly asked for.

Opt-in by design: the deterministic suite must stay offline, and this one opens
real Checkout Sessions. Point it at a **sandbox** and enable it with
`LIYAN_LIVE_STRIPE=1`:

    LIYAN_LIVE_STRIPE=1 .venv/bin/python -m pytest apps/server/tests/test_stripe_live_contract.py

It exists because the double cannot tell you the three things this integration
actually depends on: that the secret key works, that every configured Price id
exists in the account the key belongs to, and that the money those Prices charge
is the money `docs/operations/credits.md` says an 额度包 costs. A pack whose
Price was edited in the dashboard is the failure this catches — the 额度 would
keep coming from configuration while the price stopped matching them.

An opened Session is left behind and expires on its own. Nothing is charged: a
Session is an intent to pay, and nobody pays it.
"""

import os

import pytest

from liyan_server.billing.packs import CreditPack, configured_packs
from liyan_server.billing.stripe_api import HttpStripeApi, StripeApi
from liyan_server.settings import Settings

pytestmark = pytest.mark.skipif(
    os.environ.get("LIYAN_LIVE_STRIPE") != "1",
    reason="Set LIYAN_LIVE_STRIPE=1 to run the live Stripe contract check.",
)

#: What one dollar buys, from `docs/operations/credits.md`. The whole margin
#: rests on this holding for every 额度包, and it is one multiplication away from
#: being checkable — so it is checked rather than trusted.
CREDITS_PER_DOLLAR_PAID = 400


@pytest.fixture
def settings() -> Settings:
    configured = Settings()
    assert configured.stripe_secret_key, "LIYAN_LIVE_STRIPE is set but no secret key is."
    assert configured.stripe_credit_packs, "LIYAN_LIVE_STRIPE is set but no 额度包 are."
    assert not configured.stripe_secret_key.startswith("sk_live_"), (
        "Point this at a sandbox. It opens Checkout Sessions."
    )
    return configured


@pytest.fixture
def stripe(settings: Settings) -> StripeApi:
    return HttpStripeApi(
        secret_key=settings.stripe_secret_key,
        base_url=settings.stripe_api_base_url,
        timeout_seconds=settings.stripe_timeout_seconds,
    )


def packs(settings: Settings) -> tuple[CreditPack, ...]:
    return configured_packs(settings)


def test_every_configured_额度包_exists_in_this_account(
    settings: Settings, stripe: StripeApi
) -> None:
    """A Price id that is only in `.env` is an 额度包 nobody can buy, and it fails
    at the user's click rather than at deploy."""
    for pack in packs(settings):
        price = stripe.retrieve_price(pack.price_id)
        assert price["id"] == pack.price_id
        assert price["active"] is True, f"{pack.price_id} is archived"
        assert price.get("recurring") is None, (
            f"{pack.price_id} is recurring — 额度包 are bought in `payment` mode, "
            "because WeChat Pay cannot back a subscription at all."
        )


def test_the_money_a_price_charges_matches_the_额度_it_is_configured_for(
    settings: Settings, stripe: StripeApi
) -> None:
    """The two halves of an 额度包 live apart on purpose — the price in Stripe,
    the 额度 in configuration — and this is the one place they are compared."""
    for pack in packs(settings):
        price = stripe.retrieve_price(pack.price_id)
        assert price["currency"] == "usd", "credits.md prices every 额度包 in USD"
        dollars = int(price["unit_amount"]) / 100
        assert pack.credits == dollars * CREDITS_PER_DOLLAR_PAID, (
            f"{pack.price_id} charges ${dollars:.2f} for {pack.credits} 额度, which is "
            f"{pack.credits / dollars:.0f} per dollar rather than {CREDITS_PER_DOLLAR_PAID}."
        )


def test_a_checkout_session_opens_and_carries_the_user_it_was_opened_for(
    settings: Settings, stripe: StripeApi
) -> None:
    """The round trip the double cannot make: Stripe accepts the form this
    adapter builds, and hands back a URL and the metadata fulfillment reads."""
    pack = packs(settings)[0]
    user_id = "00000000-0000-4000-8000-000000000001"

    opened = stripe.create_checkout_session(
        price_id=pack.price_id,
        user_id=user_id,
        success_url="https://example.invalid/account?checkout={CHECKOUT_SESSION_ID}",
        cancel_url="https://example.invalid/account?checkout=cancelled",
    )

    assert opened.url.startswith("https://")
    read_back = stripe.retrieve_checkout_session(opened.id)
    assert read_back["mode"] == "payment"
    assert read_back["metadata"]["liyan_user_id"] == user_id
    # The expansion fulfillment depends on. Without it there is no Price in the
    # answer, and the Price is the only thing allowed to decide the 额度.
    assert read_back["line_items"]["data"][0]["price"]["id"] == pack.price_id
