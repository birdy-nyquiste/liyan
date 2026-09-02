"""The Stripe adapter: two calls out, and one signature checked on the way in.

Thin on purpose, in the shape `publication/blog.py` already uses — a Protocol
the rest of the package depends on, an httpx implementation of it, and failures
that say which kind they are. 立言阁 asks Stripe for exactly two things (open a
Checkout Session, and read one back) and Stripe tells it one thing (a payment
happened), so a full SDK would be a dependency carrying a hundred resources to
serve three.

The signature check is the part worth reading. `POST /webhooks/stripe` is the
only unauthenticated endpoint in this server that moves money, so its whole
defence is that the body was signed by a secret only Stripe holds. It is
verified against the **raw bytes** of the request — re-serializing parsed JSON
produces different bytes and a signature that never matches — and compared with
`hmac.compare_digest`, because a comparison that returns early leaks the digest
one byte at a time to anyone willing to ask often enough.
"""

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from liyan_server.settings import Settings

#: How stale a signed timestamp may be. Stripe's own default, and it is a replay
#: window rather than a clock allowance: a captured request stops working after
#: it, so a proxy log leaking one body is not a way to credit 额度 forever.
SIGNATURE_TOLERANCE_SECONDS = 300

UNAVAILABLE_MESSAGE = "支付服务暂时无法访问，请稍后重试。"
UNCONFIGURED_MESSAGE = "购买功能尚未配置，请联系管理员。"


class StripeUnavailable(Exception):
    """Stripe could not be reached, or answered in a way this cannot use.

    Always safe to retry: nothing here creates a payment, so a failed call means
    a Checkout Session that was not opened, not one whose fate is unknown.
    """


class InvalidSignature(Exception):
    """A webhook body that Stripe did not sign, or did not sign recently."""


@dataclass(frozen=True)
class CheckoutSession:
    """A Session that has been opened, and the URL that is the point of it."""

    id: str
    url: str


class StripeApi(Protocol):
    def create_checkout_session(
        self,
        *,
        price_id: str,
        user_id: str,
        success_url: str,
        cancel_url: str,
        customer_email: str | None = None,
    ) -> CheckoutSession: ...

    def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]: ...

    def retrieve_price(self, price_id: str) -> dict[str, Any]: ...


class HttpStripeApi:
    """Stripe over its form-encoded REST API.

    Form encoding rather than JSON because that is the only body Stripe's API
    accepts; nested fields are the bracketed keys built below.
    """

    def __init__(
        self,
        *,
        secret_key: str,
        base_url: str = "https://api.stripe.com",
        timeout_seconds: int = 30,
        client: httpx.Client | None = None,
    ) -> None:
        self._secret_key = secret_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client = client

    def create_checkout_session(
        self,
        *,
        price_id: str,
        user_id: str,
        success_url: str,
        cancel_url: str,
        customer_email: str | None = None,
    ) -> CheckoutSession:
        """Open one Checkout Session for one 额度包.

        `mode=payment`, never `subscription` — `docs/operations/credits.md`
        explains that this is a constraint rather than a preference: WeChat Pay
        cannot be saved for off-session use and so cannot back a subscription at
        all.

        The metadata carries the user's id and nothing else that matters. It is
        how fulfillment knows *whom* to credit; how much is read from the Price,
        server-side, in `packs.py`. A client that could influence this object
        must not be able to influence the amount.

        Promotion codes are accepted, and what that means is worth stating: a
        coupon changes what the user pays and not what they bought. 额度 are
        credited from the Price on the line item, so a half-price code buys the
        pack's whole 额度 for half the money — which is what a coupon is. Nothing
        here needs to know a code was used, and fulfillment must not start
        reading `amount_total`, or a discount would quietly become a smaller
        pack.
        """
        form = {
            "mode": "payment",
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
            "success_url": success_url,
            "cancel_url": cancel_url,
            # Stripe hides the code field unless asked, so a code 立言阁 issued
            # would be unusable at the only place it could be typed.
            "allow_promotion_codes": "true",
            "metadata[liyan_user_id]": user_id,
            # Repeated on the PaymentIntent so a refund reaching this server as a
            # charge event can still name the user, without walking back to the
            # Session that opened it.
            "payment_intent_data[metadata][liyan_user_id]": user_id,
        }
        if customer_email:
            form["customer_email"] = customer_email
        payload = self._post("/v1/checkout/sessions", form)
        session_id = payload.get("id")
        url = payload.get("url")
        if not isinstance(session_id, str) or not isinstance(url, str):
            raise StripeUnavailable("checkout session came back without an id and a url")
        return CheckoutSession(id=session_id, url=url)

    def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]:
        """Read a Session back, with its line items expanded.

        Fulfillment does this rather than trusting the event body, because the
        Session in a webhook payload carries no `line_items` — and the line item
        is where the Price is, which is the only thing allowed to decide how much
        额度 a payment bought.
        """
        return self._get(f"/v1/checkout/sessions/{session_id}", {"expand[]": "line_items"})

    def retrieve_price(self, price_id: str) -> dict[str, Any]:
        """What one 额度包 costs in money, which is Stripe's half of it.

        The workbench shows this beside the 额度 count, and the 额度 count comes
        from `packs.py`. Neither number is ever read from the other's source:
        `CONTEXT.md` calls the price the user's side of the exchange and the
        amount 立言阁's, and this is that sentence in two API calls.
        """
        return self._get(f"/v1/prices/{price_id}", {})

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if not self._secret_key:
            raise StripeUnavailable("no Stripe secret key is configured")
        try:
            if self._client is not None:
                response = self._client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers={"Authorization": f"Bearer {self._secret_key}"},
                    **kwargs,
                )
            else:
                with httpx.Client(timeout=self._timeout_seconds) as client:
                    response = client.request(
                        method,
                        f"{self._base_url}{path}",
                        headers={"Authorization": f"Bearer {self._secret_key}"},
                        **kwargs,
                    )
        except httpx.HTTPError as error:
            raise StripeUnavailable(str(error)) from error
        if response.status_code >= 400:
            raise StripeUnavailable(
                f"Stripe answered {response.status_code}: {response.text[:500]}"
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise StripeUnavailable("Stripe answered with something that is not JSON") from error
        if not isinstance(payload, dict):
            raise StripeUnavailable("Stripe answered with something that is not an object")
        return payload

    def _post(self, path: str, form: dict[str, str]) -> dict[str, Any]:
        return self._request("POST", path, data=form)

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        return self._request("GET", path, params=params)


def verify_signature(
    *,
    payload: bytes,
    signature_header: str,
    secret: str,
    now: float | None = None,
    tolerance_seconds: int = SIGNATURE_TOLERANCE_SECONDS,
) -> dict[str, Any]:
    """The signed event this body carries, or `InvalidSignature` and nothing else.

    Returning the parsed event only on success is the point: there is no way to
    reach the event body without having proved it was signed, so no later
    refactor can accidentally fulfill an unverified one.

    A header may carry several `v1` signatures during a secret rotation, and any
    one of them matching is a match.
    """
    if not secret:
        raise InvalidSignature("no webhook signing secret is configured")

    timestamp: str | None = None
    signatures: list[str] = []
    for part in signature_header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            signatures.append(value)
    if timestamp is None or not signatures:
        raise InvalidSignature("signature header is missing a timestamp or a v1 signature")

    try:
        signed_at = int(timestamp)
    except ValueError as error:
        raise InvalidSignature("signature timestamp is not a number") from error
    if abs((now if now is not None else time.time()) - signed_at) > tolerance_seconds:
        raise InvalidSignature("signature timestamp is outside the tolerance")

    expected = hmac.new(
        secret.encode("utf-8"),
        timestamp.encode("utf-8") + b"." + payload,
        hashlib.sha256,
    ).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise InvalidSignature("no signature in the header matches this body")

    try:
        event = json.loads(payload)
    except ValueError as error:
        raise InvalidSignature("signed body is not JSON") from error
    if not isinstance(event, dict):
        raise InvalidSignature("signed body is not an object")
    return event


def signature_header_for(payload: bytes, secret: str, *, timestamp: int) -> str:
    """The header Stripe would have sent for this body.

    Test scaffolding kept beside the verifier it exercises, so a test proves the
    verifier against a signature built the way the specification describes rather
    than against the verifier's own internals.
    """
    signature = hmac.new(
        secret.encode("utf-8"),
        str(timestamp).encode("utf-8") + b"." + payload,
        hashlib.sha256,
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


class UnconfiguredStripeApi:
    """What stands in when no secret key is set.

    A deployment without Stripe is legitimate — `README.md` lists what each
    blank setting costs — so buying refuses in words rather than raising
    AttributeError on a None.
    """

    def create_checkout_session(
        self,
        *,
        price_id: str,
        user_id: str,
        success_url: str,
        cancel_url: str,
        customer_email: str | None = None,
    ) -> CheckoutSession:
        raise StripeUnavailable(UNCONFIGURED_MESSAGE)

    def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]:
        raise StripeUnavailable(UNCONFIGURED_MESSAGE)

    def retrieve_price(self, price_id: str) -> dict[str, Any]:
        raise StripeUnavailable(UNCONFIGURED_MESSAGE)


def stripe_api_for(settings: Settings) -> StripeApi:
    """The adapter this deployment's configuration calls for."""
    if not settings.stripe_secret_key:
        return UnconfiguredStripeApi()
    return HttpStripeApi(
        secret_key=settings.stripe_secret_key,
        base_url=settings.stripe_api_base_url,
        timeout_seconds=settings.stripe_timeout_seconds,
    )
