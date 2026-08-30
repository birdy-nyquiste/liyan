"""What a Stripe webhook does to the ledger.

Four rules from `docs/operations/credits.md` are implemented here, and each one
is a way this goes wrong quietly rather than loudly:

**The 额度 amount is derived on the server from the Stripe Price.** The Session
in a webhook payload has no `line_items`, so fulfillment reads the Session back
from Stripe with them expanded, takes the Price id, and looks it up in
`packs.py`. Not from the event body, not from metadata, not from anything a
client could have influenced.

**Fulfillment happens here, never on the success redirect.** A user who closes
the tab after paying has still paid.

**Both completion events are handled**, because Alipay and WeChat Pay settle
late: `checkout.session.completed` covers the common case and
`checkout.session.async_payment_succeeded` covers the delayed one.

**Redelivery is a collision, not a double credit.** Every entry written here
carries a `stripe_reference` under a unique index, and the reference names the
*state* being recorded rather than the delivery that reported it.

Nothing in this module raises on an event it does not recognise. A webhook
endpoint that 500s on an unfamiliar event type teaches Stripe to retry it
forever, and the retries bury the deliveries that matter.
"""

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from liyan_server import credits
from liyan_server.billing.packs import pack_for
from liyan_server.billing.stripe_api import StripeApi
from liyan_server.database import User
from liyan_server.settings import Settings

logger = logging.getLogger(__name__)

#: Where the user's id rides on a Checkout Session. Set server-side when the
#: Session is opened; it says *whom* to credit and never how much.
USER_METADATA_KEY = "liyan_user_id"

#: Everything this endpoint acts on. Anything else is acknowledged and dropped —
#: a subscribed event type nobody handles is noise, not an error.
HANDLED_EVENTS = frozenset(
    {
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
        "checkout.session.async_payment_failed",
        "charge.refunded",
        "charge.dispute.created",
    }
)


@dataclass(frozen=True)
class Outcome:
    """What one delivery did, in the words its log line uses.

    `credited` is the 额度 that moved, and zero is the ordinary answer: a
    redelivery, an event nobody handles, or a payment still pending all leave
    the ledger alone and none of them is a failure.
    """

    action: str
    credited: int = 0
    detail: str = ""


def handle_event(
    session: Session,
    settings: Settings,
    stripe_api: StripeApi,
    event: dict[str, Any],
) -> Outcome:
    """Apply one verified Stripe event to the ledger.

    The caller has already proved the signature. This decides what the event
    means and writes at most one entry for it.
    """
    event_type = event.get("type")
    body = event.get("data", {}).get("object", {})
    if not isinstance(body, dict) or not isinstance(event_type, str):
        return Outcome(action="malformed", detail="event carried no object")

    if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        return _fulfill(session, settings, stripe_api, body)
    if event_type == "checkout.session.async_payment_failed":
        # Nothing to reverse: an async payment is only ever credited once it has
        # succeeded, so a failure here has no ledger entry to undo.
        return Outcome(action="payment_failed", detail=str(body.get("id", "")))
    if event_type == "charge.refunded":
        return _reclaim_refund(session, body)
    if event_type == "charge.dispute.created":
        return _reclaim_dispute(session, body)
    return Outcome(action="ignored", detail=event_type)


def _fulfill(
    session: Session,
    settings: Settings,
    stripe_api: StripeApi,
    checkout_session: dict[str, Any],
) -> Outcome:
    """Credit 购买额度 for one paid Checkout Session."""
    session_id = checkout_session.get("id")
    if not isinstance(session_id, str):
        return Outcome(action="malformed", detail="checkout session carried no id")

    # `completed` fires for an Alipay or WeChat Pay Session while the payment is
    # still processing. Crediting there would hand out 额度 for money that has
    # not arrived and may never; the matching `async_payment_succeeded` is what
    # says it did.
    payment_status = checkout_session.get("payment_status")
    if payment_status not in {"paid", "no_payment_required"}:
        return Outcome(action="not_yet_paid", detail=f"{session_id} is {payment_status}")

    owner_id = _owner_of(session, checkout_session)
    if owner_id is None:
        # The money is real and the account it was for is not. Nothing can be
        # credited, and a silent drop would make it unfindable, so this is the
        # one outcome that logs at error.
        logger.error(
            "stripe_fulfillment_without_user",
            extra={"checkout_session": session_id},
        )
        return Outcome(action="unknown_user", detail=session_id)

    payment_reference = _payment_reference(checkout_session)
    if payment_reference is None:
        return Outcome(action="malformed", detail=f"{session_id} named no payment")

    # Cheap and first: a redelivery is the common case, and it should not cost a
    # round trip to Stripe to discover.
    if credits.find_by_reference(session, payment_reference) is not None:
        return Outcome(action="already_credited", detail=payment_reference)

    # Not caught, deliberately. A `StripeUnavailable` here leaves the endpoint
    # answering 500, which is exactly what makes Stripe retry the delivery.
    # Swallowing it would acknowledge a payment this server never credited, and
    # guessing an amount instead is the one thing worse than a retry.
    expanded = stripe_api.retrieve_checkout_session(session_id)

    amount = _credits_for(settings, expanded)
    if amount is None:
        logger.error(
            "stripe_price_not_on_offer",
            extra={"checkout_session": session_id},
        )
        return Outcome(action="unknown_price", detail=session_id)

    entry = credits.purchase(
        session,
        owner_id,
        amount,
        stripe_reference=payment_reference,
    )
    if entry is None:
        return Outcome(action="already_credited", detail=payment_reference)
    return Outcome(action="credited", credited=amount, detail=payment_reference)


def _owner_of(session: Session, checkout_session: dict[str, Any]) -> UUID | None:
    """The user this Session was opened for, if they still exist."""
    metadata = checkout_session.get("metadata")
    raw = metadata.get(USER_METADATA_KEY) if isinstance(metadata, dict) else None
    if not isinstance(raw, str):
        return None
    try:
        owner_id = UUID(raw)
    except ValueError:
        return None
    return owner_id if session.get(User, owner_id) is not None else None


def _payment_reference(checkout_session: dict[str, Any]) -> str | None:
    """What makes this payment idempotent, and what a refund will look it up by.

    The PaymentIntent, because one payment can arrive as two events. A Session
    that required no payment has none, and falls back to its own id — which is
    equally unique and equally stable.
    """
    payment_intent = checkout_session.get("payment_intent")
    if isinstance(payment_intent, str) and payment_intent:
        return payment_intent
    if isinstance(payment_intent, dict) and isinstance(payment_intent.get("id"), str):
        return str(payment_intent["id"])
    session_id = checkout_session.get("id")
    return session_id if isinstance(session_id, str) else None


def _credits_for(settings: Settings, expanded_session: dict[str, Any]) -> int | None:
    """How much 额度 this Session's line items are worth, from the server's map.

    Nothing is credited for a Price that is not configured as an 额度包. That
    covers a retired pack and a Price belonging to another product sharing the
    Stripe account, and both should refuse rather than credit a number nobody
    chose.
    """
    line_items = expanded_session.get("line_items")
    rows = line_items.get("data") if isinstance(line_items, dict) else None
    if not isinstance(rows, list) or not rows:
        return None

    total = 0
    for row in rows:
        if not isinstance(row, dict):
            return None
        price = row.get("price")
        price_id = price.get("id") if isinstance(price, dict) else None
        if not isinstance(price_id, str):
            return None
        pack = pack_for(settings, price_id)
        if pack is None:
            return None
        quantity = row.get("quantity")
        total += pack.credits * (quantity if isinstance(quantity, int) and quantity > 0 else 1)
    return total or None


def _reclaim_refund(session: Session, charge: dict[str, Any]) -> Outcome:
    """Claw back the part of a purchase that has been refunded.

    `charge.refunded` reports the **cumulative** `amount_refunded`, so two
    partial refunds each report the total refunded so far. Reclaiming what the
    event says would reclaim the first refund twice; reclaiming the difference
    against what is already clawed back is what makes a sequence of partial
    refunds add up to exactly the whole.
    """
    charged = charge.get("amount")
    refunded = charge.get("amount_refunded")
    if not isinstance(charged, int) or not isinstance(refunded, int) or charged <= 0:
        return Outcome(action="malformed", detail="charge carried no amounts")
    return _reclaim(
        session,
        charge,
        share=refunded / charged,
        reference_suffix=f"refunded:{refunded}",
    )


def _reclaim_dispute(session: Session, dispute: dict[str, Any]) -> Outcome:
    """Claw back the whole purchase the moment it is disputed.

    The whole of it, and at `created` rather than when the dispute is lost: the
    money is already gone from 立言阁's balance while it is open, and 额度 left
    spendable in the meantime is 额度 that will have been spent by the time
    anybody knows the outcome.
    """
    dispute_id = dispute.get("id")
    return _reclaim(
        session,
        dispute,
        share=1.0,
        reference_suffix=f"dispute:{dispute_id if isinstance(dispute_id, str) else 'unknown'}",
    )


def _reclaim(
    session: Session,
    body: dict[str, Any],
    *,
    share: float,
    reference_suffix: str,
) -> Outcome:
    """The half a refund and a dispute have in common."""
    payment_intent = body.get("payment_intent")
    if not isinstance(payment_intent, str) or not payment_intent:
        return Outcome(action="malformed", detail="no payment intent to reverse")

    purchased = credits.find_by_reference(session, payment_intent)
    if purchased is None or purchased.kind != "purchase":
        # A payment this ledger never credited — a Session that failed before
        # fulfillment, or a charge belonging to another product on the same
        # Stripe account. There is nothing of 立言阁's to take back.
        return Outcome(action="nothing_to_reclaim", detail=payment_intent)

    # Rounded down, so a rounding error is always in the user's favour. Taking
    # back more than was proportionally refunded is charging somebody for a
    # remainder.
    owed = min(purchased.amount, int(purchased.amount * share))
    outstanding = owed - credits.reclaimed_against(session, payment_intent)
    if outstanding <= 0:
        return Outcome(action="already_reclaimed", detail=payment_intent)

    entry = credits.clawback(
        session,
        purchased.owner_id,
        outstanding,
        stripe_reference=f"{payment_intent}#{reference_suffix}",
    )
    if entry is None:
        return Outcome(action="already_reclaimed", detail=payment_intent)
    return Outcome(action="reclaimed", credited=-outstanding, detail=payment_intent)
