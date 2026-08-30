"""Buying 额度, and every way a webhook could get it wrong.

`docs/operations/credits.md` states four rules for this integration and each one
names a failure that is silent rather than loud — a double credit, a payment
that never lands, an amount the client chose. There is a test below for each.
"""

import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from billing_support import (
    PACK_CONFIG,
    SMALL_PRICE,
    WEBHOOK_SECRET,
    StripeSaying,
    charge_refunded_event,
    checkout_completed_event,
    dispute_created_event,
    signed,
)
from database_support import QueueSaying, migrated_database
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from liyan_server.app import create_app
from liyan_server.auth import InvalidAccessToken, VerifiedIdentity
from liyan_server.billing.stripe_api import StripeApi
from liyan_server.database import Database
from liyan_server.settings import Settings

TOKEN = "allowed-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


class DeterministicJwtVerifier:
    def __init__(self, identity: VerifiedIdentity) -> None:
        self._identity = identity

    def verify(self, token: str) -> VerifiedIdentity:
        if token != TOKEN:
            raise InvalidAccessToken
        return self._identity


def a_client(
    tmp_path: Path,
    stripe: StripeApi | None = None,
    *,
    packs: str = PACK_CONFIG,
    secret_key: str = "sk_test_x",
    signup_grant_credits: int = 0,
) -> tuple[TestClient, Database]:
    """A signed-in user whose only unusual configuration is Stripe's."""
    database_url = migrated_database(tmp_path)
    settings = Settings(
        database_url=database_url,
        allowed_emails="writer@example.com",
        stripe_secret_key=secret_key,
        stripe_webhook_secret=WEBHOOK_SECRET,
        stripe_credit_packs=packs,
        signup_grant_credits=signup_grant_credits,
        web_base_url="https://liyan.example",
    )
    client = TestClient(
        create_app(
            settings,
            jwt_verifier=DeterministicJwtVerifier(
                VerifiedIdentity(subject="supabase-user-1", email="writer@example.com")
            ),
            execution_dispatcher=QueueSaying(True),
            stripe_api=stripe or StripeSaying(),
        )
    )
    return client, Database(database_url)


def owner_of(client: TestClient) -> UUID:
    """The local user id, which is what a Checkout Session carries as metadata."""
    return UUID(client.get("/auth/me", headers=HEADERS).json()["id"])


def deliver(client: TestClient, event: dict[str, Any], *, secret: str = WEBHOOK_SECRET) -> int:
    payload, headers = signed(event, timestamp=int(time.time()), secret=secret)
    return client.post("/webhooks/stripe", content=payload, headers=headers).status_code


def balance(client: TestClient) -> int:
    return int(client.get("/account", headers=HEADERS).json()["remaining_credits"])


# ---------------------------------------------------------------- opening one


def test_checkout_carries_the_user_and_never_an_amount(tmp_path: Path) -> None:
    """The metadata says whom to credit. How much is read from the Price on this
    side, which is the whole of the rule this test guards."""
    stripe = StripeSaying()
    client, _ = a_client(tmp_path, stripe)
    owner = owner_of(client)

    response = client.post(
        "/account/checkout-session",
        json={"price_id": SMALL_PRICE},
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["url"].startswith("https://checkout.stripe.com/")
    opened = stripe.opened[0]
    assert opened["user_id"] == str(owner)
    assert opened["price_id"] == SMALL_PRICE
    assert "2000" not in str(opened) and "credits" not in str(opened)


def test_checkout_returns_the_user_to_their_account_page(tmp_path: Path) -> None:
    """Both ways back land on `/account`, which is where the balance is and where
    a return from a payment polls for it."""
    stripe = StripeSaying()
    client, _ = a_client(tmp_path, stripe)

    client.post("/account/checkout-session", json={"price_id": SMALL_PRICE}, headers=HEADERS)

    opened = stripe.opened[0]
    assert opened["success_url"] == "https://liyan.example/account?checkout={CHECKOUT_SESSION_ID}"
    assert opened["cancel_url"] == "https://liyan.example/account?checkout=cancelled"


def test_a_price_this_deployment_does_not_sell_is_refused_before_any_money_moves(
    tmp_path: Path,
) -> None:
    """Refused here rather than at fulfillment. Passing it through would open a
    Session that takes money and then credits nothing."""
    stripe = StripeSaying()
    client, _ = a_client(tmp_path, stripe)

    response = client.post(
        "/account/checkout-session",
        json={"price_id": "price_from_another_product"},
        headers=HEADERS,
    )

    assert response.status_code == 404
    assert stripe.opened == []


def test_buying_is_unavailable_rather_than_broken_when_stripe_is_not_configured(
    tmp_path: Path,
) -> None:
    """A deployment without Stripe is legitimate. It refuses in words."""
    client, _ = a_client(tmp_path, secret_key="", packs="")

    response = client.post(
        "/account/checkout-session",
        json={"price_id": SMALL_PRICE},
        headers=HEADERS,
    )

    assert response.status_code in {404, 503}
    assert client.get("/account", headers=HEADERS).status_code == 200


def test_checkout_belongs_to_a_signed_in_user(tmp_path: Path) -> None:
    client, _ = a_client(tmp_path)

    response = client.post("/account/checkout-session", json={"price_id": SMALL_PRICE})

    assert response.status_code in {401, 403}


def test_the_packs_on_offer_carry_both_halves_of_the_exchange(tmp_path: Path) -> None:
    """The 额度 from configuration, the money from Stripe. Neither is read from
    the other's source."""
    client, _ = a_client(tmp_path, StripeSaying(unit_amount=500))

    packs = client.get("/account/credit-packs", headers=HEADERS).json()["packs"]

    assert [pack["credits"] for pack in packs] == [2_000, 8_000]
    assert packs[0]["unit_amount"] == 500
    assert packs[0]["currency"] == "usd"


# ------------------------------------------------------------------ crediting


def test_a_completed_checkout_credits_the_pack_the_price_maps_to(tmp_path: Path) -> None:
    client, _ = a_client(tmp_path)
    owner = owner_of(client)

    assert deliver(client, checkout_completed_event(owner)) == 204

    assert balance(client) == 2_000
    assert client.get("/account", headers=HEADERS).json()["is_paying_user"] is True


def test_the_amount_comes_from_the_price_and_not_from_the_event(tmp_path: Path) -> None:
    """The rule this integration exists to obey. An event claiming a larger pack
    changes nothing, because nothing reads it."""
    client, _ = a_client(tmp_path)
    owner = owner_of(client)
    event = checkout_completed_event(owner)
    event["data"]["object"]["amount_total"] = 5_000_000
    event["data"]["object"]["metadata"]["credits"] = "999999"

    deliver(client, event)

    assert balance(client) == 2_000


def test_a_redelivered_webhook_credits_once(tmp_path: Path) -> None:
    """Stripe retries. The second delivery finds the row already there."""
    client, _ = a_client(tmp_path)
    owner = owner_of(client)

    deliver(client, checkout_completed_event(owner))
    deliver(client, checkout_completed_event(owner))

    assert balance(client) == 2_000


def test_one_payment_arriving_as_two_events_credits_once(tmp_path: Path) -> None:
    """The reason the ledger keys on the PaymentIntent rather than the event id.
    Two different events, two different ids, one payment."""
    client, _ = a_client(tmp_path)
    owner = owner_of(client)

    deliver(client, checkout_completed_event(owner, event_id="evt_1"))
    deliver(
        client,
        checkout_completed_event(
            owner,
            event_id="evt_2",
            event_type="checkout.session.async_payment_succeeded",
        ),
    )

    assert balance(client) == 2_000


def test_an_async_payment_credits_only_once_it_has_actually_succeeded(
    tmp_path: Path,
) -> None:
    """Alipay and WeChat Pay complete the Session before the money arrives.
    Crediting at `completed` would hand out 额度 for a payment that may never
    settle."""
    client, _ = a_client(tmp_path)
    owner = owner_of(client)

    deliver(client, checkout_completed_event(owner, payment_status="unpaid"))
    assert balance(client) == 0

    deliver(
        client,
        checkout_completed_event(
            owner,
            event_id="evt_2",
            event_type="checkout.session.async_payment_succeeded",
        ),
    )
    assert balance(client) == 2_000


def test_an_async_payment_that_fails_leaves_the_ledger_alone(tmp_path: Path) -> None:
    client, _ = a_client(tmp_path)
    owner = owner_of(client)

    deliver(client, checkout_completed_event(owner, payment_status="unpaid"))
    status = deliver(
        client,
        checkout_completed_event(
            owner,
            event_id="evt_2",
            event_type="checkout.session.async_payment_failed",
        ),
    )

    assert status == 204
    assert balance(client) == 0


def test_a_price_that_is_not_an_额度包_credits_nothing(tmp_path: Path) -> None:
    """A live Stripe account can host another product's Prices — this one does.
    Crediting a Price nobody configured would invent an amount."""
    stripe = StripeSaying(line_items=[{"price": {"id": "price_rewritepro"}, "quantity": 1}])
    client, _ = a_client(tmp_path, stripe)
    owner = owner_of(client)

    assert deliver(client, checkout_completed_event(owner)) == 204

    assert balance(client) == 0


def test_a_quantity_above_one_credits_that_many_packs(tmp_path: Path) -> None:
    stripe = StripeSaying(line_items=[{"price": {"id": SMALL_PRICE}, "quantity": 3}])
    client, _ = a_client(tmp_path, stripe)
    owner = owner_of(client)

    deliver(client, checkout_completed_event(owner))

    assert balance(client) == 6_000


def test_a_body_stripe_did_not_sign_credits_nothing(tmp_path: Path) -> None:
    """The endpoint's whole defence. 400 rather than 500 because Stripe does not
    retry a 400, and an unsigned body will not become signed on a retry."""
    client, _ = a_client(tmp_path)
    owner = owner_of(client)

    status = deliver(client, checkout_completed_event(owner), secret="whsec_someone_elses")

    assert status == 400
    assert balance(client) == 0


def test_a_session_for_a_user_who_no_longer_exists_credits_nobody(tmp_path: Path) -> None:
    """A deleted account cannot be credited, and inventing one is worse than a
    log line an operator can find the payment from."""
    client, _ = a_client(tmp_path)

    assert deliver(client, checkout_completed_event(uuid4())) == 204

    assert balance(client) == 0


def test_an_event_nobody_handles_is_acknowledged(tmp_path: Path) -> None:
    """A webhook endpoint that 500s on an unfamiliar event teaches Stripe to
    retry it forever, and the retries bury the deliveries that matter."""
    client, _ = a_client(tmp_path)

    status = deliver(
        client,
        {"id": "evt_x", "type": "customer.created", "data": {"object": {"id": "cus_1"}}},
    )

    assert status == 204


# ---------------------------------------------------------------- taking back


def test_a_full_refund_takes_back_what_it_bought(tmp_path: Path) -> None:
    client, _ = a_client(tmp_path)
    owner = owner_of(client)
    deliver(client, checkout_completed_event(owner))

    deliver(client, charge_refunded_event(amount=500, amount_refunded=500))

    assert balance(client) == 0


def test_a_partial_refund_takes_back_its_share(tmp_path: Path) -> None:
    client, _ = a_client(tmp_path)
    owner = owner_of(client)
    deliver(client, checkout_completed_event(owner))

    deliver(client, charge_refunded_event(amount=500, amount_refunded=250))

    assert balance(client) == 1_000


def test_two_partial_refunds_add_up_to_the_whole_and_not_to_double(tmp_path: Path) -> None:
    """`charge.refunded` reports the *cumulative* amount refunded. Reclaiming
    what the event says would reclaim the first refund twice."""
    client, _ = a_client(tmp_path)
    owner = owner_of(client)
    deliver(client, checkout_completed_event(owner))

    deliver(client, charge_refunded_event(event_id="evt_r1", amount=500, amount_refunded=250))
    deliver(client, charge_refunded_event(event_id="evt_r2", amount=500, amount_refunded=500))

    assert balance(client) == 0


def test_a_redelivered_refund_takes_back_once(tmp_path: Path) -> None:
    client, _ = a_client(tmp_path)
    owner = owner_of(client)
    deliver(client, checkout_completed_event(owner))

    deliver(client, charge_refunded_event(amount=500, amount_refunded=500))
    deliver(client, charge_refunded_event(amount=500, amount_refunded=500))

    assert balance(client) == 0


def test_a_dispute_may_take_a_balance_below_zero(tmp_path: Path) -> None:
    """额度 that were spent before the dispute arrived are gone. What is left is
    a debt, and hiding it at zero would let the same person start again free."""
    client, database = a_client(tmp_path)
    owner = owner_of(client)
    deliver(client, checkout_completed_event(owner))
    assert database.engine is not None
    with Session(database.engine) as session:
        from liyan_server import credits

        credits.hold(
            session,
            owner,
            target_type="source_revision",
            target_id=uuid4(),
            input_version=1,
            attempt=1,
            credits=1_500,
        )
        session.commit()

    deliver(client, dispute_created_event())

    assert balance(client) == -1_500


def test_a_refund_for_a_payment_this_ledger_never_credited_takes_nothing(
    tmp_path: Path,
) -> None:
    """A charge belonging to another product on the same Stripe account, or a
    Session that failed before fulfillment. There is nothing of 立言阁's to take."""
    client, _ = a_client(tmp_path)
    owner_of(client)

    status = deliver(client, charge_refunded_event(payment_intent="pi_someone_elses"))

    assert status == 204
    assert balance(client) == 0


def test_赠送额度_survive_a_refund(tmp_path: Path) -> None:
    """CONTEXT.md: a refund never reclaims 赠送额度. Only what was bought."""
    client, _ = a_client(tmp_path, signup_grant_credits=150)
    owner = owner_of(client)
    deliver(client, checkout_completed_event(owner))

    deliver(client, charge_refunded_event(amount=500, amount_refunded=500))

    assert balance(client) == 150


@pytest.mark.parametrize(
    "event",
    [
        {"id": "e", "type": "checkout.session.completed", "data": {"object": {}}},
        {"id": "e", "type": "charge.refunded", "data": {"object": {}}},
        {"id": "e", "type": "charge.dispute.created", "data": {"object": {}}},
    ],
    ids=["checkout", "refund", "dispute"],
)
def test_an_event_missing_what_it_needs_is_acknowledged_rather_than_retried_forever(
    tmp_path: Path, event: dict[str, Any]
) -> None:
    client, _ = a_client(tmp_path)

    assert deliver(client, event) == 204
    assert balance(client) == 0
