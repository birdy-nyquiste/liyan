"""What an 额度包 is, and the one place that decides what a payment buys.

`docs/operations/credits.md` states the rule this module exists to enforce:
**the 额度 amount is derived on the server from the Stripe Price** — never from
anything the client sent, and never from session metadata a client could have
influenced. So a Checkout request names a Price and nothing else, and the
number of 额度 it is worth is read from here.

Keeping the amount out of Stripe is deliberate. The money side of an 额度包 is
Stripe's — currency, tax, receipts, what a payer's wallet converts it to — and
the 额度 side is 立言阁's, which is the same split `CONTEXT.md` draws when it
says the price is the user's side of the exchange and the amount is 立言阁's.
Reading the amount out of Price metadata would put a number the ledger trusts
somewhere a dashboard click can change.

Configuration is read once at startup, like 发布目标, so an operator learns
about a malformed pack when the server boots rather than when a user clicks 购买.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from liyan_server.settings import Settings


@dataclass(frozen=True)
class CreditPack:
    """One price, for one amount of 额度."""

    price_id: str
    credits: int


class CreditPacksMisconfigured(Exception):
    """Configuration that cannot be read, raised at startup and never later."""


def _parse(raw: str) -> tuple[CreditPack, ...]:
    if not raw.strip():
        return ()
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CreditPacksMisconfigured(f"LIYAN_STRIPE_CREDIT_PACKS is not JSON: {error}") from error
    if not isinstance(entries, list):
        raise CreditPacksMisconfigured("LIYAN_STRIPE_CREDIT_PACKS must be a JSON array")

    packs: list[CreditPack] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise CreditPacksMisconfigured("every 额度包 must be an object")
        price_id = entry.get("price_id")
        credits = entry.get("credits")
        if not isinstance(price_id, str) or not price_id.strip():
            raise CreditPacksMisconfigured("every 额度包 needs a price_id")
        # A pack worth nothing is configuration that took somebody's money for
        # no 额度, which is worth refusing to start over.
        if not isinstance(credits, int) or isinstance(credits, bool) or credits <= 0:
            raise CreditPacksMisconfigured(f"{price_id} needs a positive integer credits")
        if price_id in seen:
            raise CreditPacksMisconfigured(f"{price_id} is configured twice")
        seen.add(price_id)
        packs.append(CreditPack(price_id=price_id.strip(), credits=credits))
    return tuple(packs)


@lru_cache(maxsize=8)
def _cached(raw: str) -> tuple[CreditPack, ...]:
    return _parse(raw)


def configured_packs(settings: Settings) -> tuple[CreditPack, ...]:
    """Every 额度包 on offer, in the order an operator wrote them.

    That order is the order the workbench shows them in, so the cheapest way in
    stays first without the client sorting on a number it should not be
    reasoning about.
    """
    return _cached(settings.stripe_credit_packs)


def pack_for(settings: Settings, price_id: str) -> CreditPack | None:
    """What this Price is worth in 额度, or nothing if it is not on offer.

    Nothing is the answer for a Price that exists in Stripe but is not
    configured here — an old 额度包, or one belonging to another product sharing
    the account. Selling it would credit an amount nobody chose.
    """
    for pack in configured_packs(settings):
        if pack.price_id == price_id:
            return pack
    return None


type BillingState = Literal["configured", "unconfigured"]


def billing_state(settings: Settings) -> BillingState:
    """Whether this deployment can sell 额度.

    Reported by `/health/ready` and never gating, for the same reason object
    storage is not: a deployment that cannot sell 额度 still serves everything a
    user already paid for, and taking the API out of rotation over it would
    turn a missing feature into an outage.

    All three settings are required together. A secret key without a signing
    secret is the dangerous half-configuration — Checkout would open and nothing
    would ever credit — so it reports as unconfigured rather than as most of the
    way there.
    """
    if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
        return "unconfigured"
    return "configured" if configured_packs(settings) else "unconfigured"
