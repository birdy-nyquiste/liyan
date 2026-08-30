"""A Stripe that answers from a script, so the tests are about 立言阁.

The real adapter is exercised against the real API by
`test_stripe_live_contract.py`, which is opt-in. Everything else here is about
what this server does with an answer, and that is worth testing without a
network.
"""

import json
from typing import Any
from uuid import UUID

from liyan_server.billing.stripe_api import CheckoutSession, signature_header_for

#: The sandbox Price ids, so a test and `.env.example` disagree loudly.
SMALL_PRICE = "price_small"
PACK_CONFIG = json.dumps(
    [
        {"price_id": SMALL_PRICE, "credits": 2_000},
        {"price_id": "price_medium", "credits": 8_000},
    ]
)

WEBHOOK_SECRET = "whsec_test_secret"


class StripeSaying:
    """Stripe with a fixed opinion, and a record of what it was asked."""

    def __init__(
        self,
        *,
        line_items: list[dict[str, Any]] | None = None,
        payment_status: str = "paid",
        unit_amount: int = 500,
    ) -> None:
        self.line_items = (
            line_items
            if line_items is not None
            else [{"price": {"id": SMALL_PRICE}, "quantity": 1}]
        )
        self.payment_status = payment_status
        self.unit_amount = unit_amount
        self.opened: list[dict[str, Any]] = []
        self.retrieved: list[str] = []

    def create_checkout_session(
        self,
        *,
        price_id: str,
        user_id: str,
        success_url: str,
        cancel_url: str,
        customer_email: str | None = None,
    ) -> CheckoutSession:
        self.opened.append(
            {
                "price_id": price_id,
                "user_id": user_id,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "customer_email": customer_email,
            }
        )
        return CheckoutSession(id="cs_test_1", url="https://checkout.stripe.com/c/pay/cs_test_1")

    def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]:
        self.retrieved.append(session_id)
        return {
            "id": session_id,
            "payment_status": self.payment_status,
            "line_items": {"data": self.line_items},
        }

    def retrieve_price(self, price_id: str) -> dict[str, Any]:
        return {"id": price_id, "unit_amount": self.unit_amount, "currency": "usd"}


def checkout_completed_event(
    owner_id: UUID,
    *,
    event_id: str = "evt_1",
    session_id: str = "cs_test_1",
    payment_intent: str = "pi_test_1",
    payment_status: str = "paid",
    event_type: str = "checkout.session.completed",
) -> dict[str, Any]:
    return {
        "id": event_id,
        "type": event_type,
        "data": {
            "object": {
                "id": session_id,
                "object": "checkout.session",
                "payment_status": payment_status,
                "payment_intent": payment_intent,
                "metadata": {"liyan_user_id": str(owner_id)},
            }
        },
    }


def charge_refunded_event(
    *,
    event_id: str = "evt_refund",
    payment_intent: str = "pi_test_1",
    amount: int = 500,
    amount_refunded: int = 500,
) -> dict[str, Any]:
    return {
        "id": event_id,
        "type": "charge.refunded",
        "data": {
            "object": {
                "id": "ch_test_1",
                "object": "charge",
                "payment_intent": payment_intent,
                "amount": amount,
                "amount_refunded": amount_refunded,
            }
        },
    }


def dispute_created_event(
    *,
    event_id: str = "evt_dispute",
    dispute_id: str = "du_test_1",
    payment_intent: str = "pi_test_1",
) -> dict[str, Any]:
    return {
        "id": event_id,
        "type": "charge.dispute.created",
        "data": {
            "object": {
                "id": dispute_id,
                "object": "dispute",
                "charge": "ch_test_1",
                "payment_intent": payment_intent,
            }
        },
    }


def signed(
    event: dict[str, Any], *, timestamp: int, secret: str = WEBHOOK_SECRET
) -> tuple[bytes, dict[str, str]]:
    """A body and the header Stripe would have sent with it.

    The body is returned as the exact bytes that were signed, because the
    verifier checks those and re-serializing the parsed event produces
    different ones.
    """
    payload = json.dumps(event).encode("utf-8")
    return payload, {
        "stripe-signature": signature_header_for(payload, secret, timestamp=timestamp),
        "content-type": "application/json",
    }
