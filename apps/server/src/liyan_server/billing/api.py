"""Buying 额度: one endpoint a user reaches, and one only Stripe reaches.

The split matters. `POST /account/checkout-session` is authenticated and does
nothing but open a Session — no 额度 move, and a client that calls it a hundred
times has bought nothing. `POST /webhooks/stripe` is unauthenticated, because
Stripe holds no credential of this server's, and it is the only place 额度 are
credited. Its whole defence is the signature, and it verifies the raw body.

The success redirect deliberately grants nothing. It is a page a user lands on;
what it does about the balance is in `docs/design/credits-in-the-workbench.md`,
and the short version is that it polls, because Alipay and WeChat Pay settle
after the redirect has already arrived.
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from liyan_server.authentication import CurrentUserDependency
from liyan_server.billing import fulfillment
from liyan_server.billing.packs import configured_packs, pack_for
from liyan_server.billing.stripe_api import (
    InvalidSignature,
    StripeApi,
    StripeUnavailable,
    verify_signature,
)
from liyan_server.database import Database, User
from liyan_server.settings import Settings

logger = logging.getLogger(__name__)

UNKNOWN_PACK_MESSAGE = "该额度包不存在。"


class CheckoutRequest(BaseModel):
    #: A Price, and nothing about what it is worth. What it buys is decided by
    #: `packs.py` on this side, which is the whole of the rule in
    #: `docs/operations/credits.md` that says never to trust the client for it.
    price_id: str = Field(min_length=1, max_length=255)


class CheckoutResponse(BaseModel):
    #: Where to send the user. Stripe hosts the page; 立言阁 never sees a card.
    url: str


class CreditPackResponse(BaseModel):
    price_id: str
    #: 立言阁's side of the exchange, from configuration.
    credits: int
    #: The user's side, from Stripe, in the smallest unit of the currency.
    #: Absent when Stripe cannot be reached — the 额度包 is still real and still
    #: buyable, and Checkout will show the price authoritatively either way.
    unit_amount: int | None
    currency: str | None


class CreditPacksResponse(BaseModel):
    packs: list[CreditPackResponse]


def billing_router(
    settings: Settings,
    database: Database,
    current_user: CurrentUserDependency,
    stripe_api: StripeApi,
) -> APIRouter:
    router = APIRouter(tags=["billing"])
    #: Prices change rarely and this is read on every visit to `/account`, so
    #: one answer is kept per Price for the life of the process. A price change
    #: takes effect on the next deploy, which is also when the 额度 it maps to
    #: would change.
    price_cache: dict[str, dict[str, Any]] = {}

    def _price(price_id: str) -> dict[str, Any] | None:
        if price_id not in price_cache:
            try:
                price_cache[price_id] = stripe_api.retrieve_price(price_id)
            except StripeUnavailable:
                # The reason, not the response body: `observability.py` keeps
                # unbounded provider text out of logs on purpose, and a Stripe
                # error body is exactly the sort of thing that allowlist is for.
                logger.warning(
                    "stripe_price_unavailable",
                    extra={"price_id": price_id, "error_code": "stripe_unavailable"},
                )
                return None
        return price_cache[price_id]

    @router.get(
        "/account/credit-packs",
        operation_id="list_credit_packs",
        response_model=CreditPacksResponse,
    )
    def list_credit_packs(
        _: Annotated[User, Depends(current_user)],
    ) -> CreditPacksResponse:
        """Every 额度包 on offer, in the order an operator configured them.

        Empty is a legitimate answer, not an error: a deployment without Stripe
        configured sells nothing, and the workbench says so rather than
        offering a button that cannot work.
        """
        packs = []
        for pack in configured_packs(settings):
            price = _price(pack.price_id)
            unit_amount = price.get("unit_amount") if price else None
            currency = price.get("currency") if price else None
            packs.append(
                CreditPackResponse(
                    price_id=pack.price_id,
                    credits=pack.credits,
                    unit_amount=unit_amount if isinstance(unit_amount, int) else None,
                    currency=currency if isinstance(currency, str) else None,
                )
            )
        return CreditPacksResponse(packs=packs)

    @router.post(
        "/account/checkout-session",
        operation_id="create_checkout_session",
        response_model=CheckoutResponse,
    )
    def create_checkout_session(
        body: CheckoutRequest,
        user: Annotated[User, Depends(current_user)],
    ) -> CheckoutResponse:
        """Open a Stripe Checkout Session for one 额度包.

        A Price this deployment does not sell is refused here rather than at
        fulfillment. Passing it through would open a Session that takes money
        and then credits nothing, which is the worst available ordering of
        those two events.
        """
        if pack_for(settings, body.price_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=UNKNOWN_PACK_MESSAGE,
            )
        base = settings.web_base_url.rstrip("/")
        try:
            checkout = stripe_api.create_checkout_session(
                price_id=body.price_id,
                user_id=str(user.id),
                # `{CHECKOUT_SESSION_ID}` is substituted by Stripe, not by this
                # server. `/account` reads it back only to know it is returning
                # from a payment; it grants nothing on the strength of it.
                success_url=f"{base}/account?checkout={{CHECKOUT_SESSION_ID}}",
                cancel_url=f"{base}/account?checkout=cancelled",
                customer_email=user.email or None,
            )
        except StripeUnavailable as error:
            logger.warning(
                "stripe_checkout_unavailable",
                extra={"price_id": body.price_id, "error_code": "stripe_unavailable"},
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(error),
            ) from error
        return CheckoutResponse(url=checkout.url)

    @router.post("/webhooks/stripe", operation_id="receive_stripe_webhook", include_in_schema=False)
    async def receive_stripe_webhook(
        request: Request,
        session: Annotated[Session, Depends(database.session)],
    ) -> Response:
        """The only place 额度 are bought, and the only unauthenticated one.

        Verified against the raw bytes — a body re-serialized from parsed JSON
        signs differently and would never match.

        A 400 for a bad signature is deliberate: Stripe does not retry it, and
        an unsigned body is not a delivery that will succeed later. Everything
        this server *can* be at fault for answers 500, so Stripe retries it.
        """
        payload = await request.body()
        try:
            event = verify_signature(
                payload=payload,
                signature_header=request.headers.get("stripe-signature", ""),
                secret=settings.stripe_webhook_secret,
            )
        except InvalidSignature as error:
            logger.warning(
                "stripe_webhook_rejected", extra={"error_code": "invalid_signature"}
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="signature could not be verified",
            ) from error

        outcome = fulfillment.handle_event(session, settings, stripe_api, event)
        session.commit()
        logger.info(
            "stripe_webhook_handled",
            extra={
                "event_type": event.get("type"),
                "event_id": event.get("id"),
                "action": outcome.action,
                "credits": outcome.credited,
                "payment_reference": outcome.detail,
            },
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
