"""The exact form one Checkout Session is opened with.

Everything else about buying 额度 is tested through a double that records the
*arguments* this adapter is called with. That leaves the form itself — the only
part Stripe actually reads — covered nowhere offline: a misspelled field is not
an error there, it is a field Stripe ignores, and the failure is a Checkout page
that quietly lacks something.
"""

from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from liyan_server.billing.stripe_api import HttpStripeApi, StripeUnavailable

SESSION = {"id": "cs_test_1", "url": "https://checkout.stripe.com/c/pay/cs_test_1"}


def opened_form(answer: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """The form body the adapter sends when it opens one Session."""
    sent: dict[str, list[str]] = {}

    def record(request: httpx.Request) -> httpx.Response:
        sent.update(parse_qs(request.content.decode()))
        return httpx.Response(200, json=answer or SESSION)

    client = httpx.Client(transport=httpx.MockTransport(record))
    api = HttpStripeApi(secret_key="sk_test", client=client)
    api.create_checkout_session(
        price_id="price_small",
        user_id="user-1",
        success_url="https://liyan.example/account?checkout={CHECKOUT_SESSION_ID}",
        cancel_url="https://liyan.example/account?checkout=cancelled",
        customer_email="writer@example.com",
    )
    return sent


def test_a_session_accepts_a_promotion_code() -> None:
    """Stripe hides the code field unless asked, so a code 立言阁 issued would be
    unusable at the only place a buyer could type it."""
    assert opened_form()["allow_promotion_codes"] == ["true"]


def test_a_session_is_a_payment_and_never_a_subscription() -> None:
    """`docs/operations/credits.md`: WeChat Pay cannot be saved for off-session
    use, so a subscription is not available rather than not preferred."""
    assert opened_form()["mode"] == ["payment"]


def test_a_session_carries_the_user_on_itself_and_on_the_payment() -> None:
    """Fulfillment reads the Session; a refund arrives as a charge event and has
    only the PaymentIntent to name the user from."""
    form = opened_form()

    assert form["metadata[liyan_user_id]"] == ["user-1"]
    assert form["payment_intent_data[metadata][liyan_user_id]"] == ["user-1"]


def test_a_session_names_one_price_and_never_an_amount() -> None:
    """How much 额度 a payment buys is read from the Price, server-side. A form
    that carried an amount would be a second answer to that question."""
    form = opened_form()

    assert form["line_items[0][price]"] == ["price_small"]
    assert form["line_items[0][quantity]"] == ["1"]
    assert not [key for key in form if "amount" in key]


def test_a_session_that_comes_back_without_a_url_is_unusable() -> None:
    """The URL is the entire point of opening one: nothing else here can send a
    buyer to Stripe."""
    with pytest.raises(StripeUnavailable):
        opened_form({"id": "cs_test_1"})
