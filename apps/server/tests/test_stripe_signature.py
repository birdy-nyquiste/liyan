"""The one thing standing between an open endpoint and free 额度.

`POST /webhooks/stripe` is unauthenticated by necessity — Stripe holds no
credential of this server's — so every one of these is a way somebody credits
themselves if the verifier is wrong.
"""

import json
import time

import pytest
from billing_support import WEBHOOK_SECRET, signed

from liyan_server.billing.stripe_api import InvalidSignature, verify_signature


def test_a_body_stripe_signed_is_returned_as_the_event_it_carries() -> None:
    now = int(time.time())
    payload, headers = signed({"id": "evt_1", "type": "checkout.session.completed"}, timestamp=now)

    event = verify_signature(
        payload=payload,
        signature_header=headers["stripe-signature"],
        secret=WEBHOOK_SECRET,
        now=now,
    )

    assert event["id"] == "evt_1"


def test_the_event_is_reachable_only_through_the_verifier() -> None:
    """Returning the parsed event only on success is the design: there is no way
    to hold the body without having proved it was signed."""
    now = int(time.time())
    payload, headers = signed({"id": "evt_1"}, timestamp=now)

    with pytest.raises(InvalidSignature):
        verify_signature(
            payload=payload,
            signature_header=headers["stripe-signature"],
            secret="whsec_someone_elses",
            now=now,
        )


def test_a_body_changed_after_signing_is_refused() -> None:
    """The amount a webhook reports is not what decides 额度, but a body that can
    be edited in flight is a hole regardless of what is currently read from it."""
    now = int(time.time())
    payload, headers = signed({"id": "evt_1", "type": "charge.refunded"}, timestamp=now)
    tampered = payload.replace(b"evt_1", b"evt_2")

    with pytest.raises(InvalidSignature):
        verify_signature(
            payload=tampered,
            signature_header=headers["stripe-signature"],
            secret=WEBHOOK_SECRET,
            now=now,
        )


def test_a_body_re_serialized_from_its_own_event_no_longer_verifies() -> None:
    """Why the endpoint reads `await request.body()` and never the parsed model:
    JSON that means the same thing is not the same bytes, and bytes are signed."""
    now = int(time.time())
    event = {"id": "evt_1", "type": "checkout.session.completed"}
    payload, headers = signed(event, timestamp=now)
    re_serialized = json.dumps(event, indent=2).encode("utf-8")

    assert re_serialized != payload
    with pytest.raises(InvalidSignature):
        verify_signature(
            payload=re_serialized,
            signature_header=headers["stripe-signature"],
            secret=WEBHOOK_SECRET,
            now=now,
        )


def test_an_old_signature_is_refused_however_valid_it_was() -> None:
    """The tolerance is a replay window, not a clock allowance: a captured body
    from a proxy log stops being a way to credit 额度."""
    signed_at = int(time.time()) - 3_600
    payload, headers = signed({"id": "evt_1"}, timestamp=signed_at)

    with pytest.raises(InvalidSignature):
        verify_signature(
            payload=payload,
            signature_header=headers["stripe-signature"],
            secret=WEBHOOK_SECRET,
            now=signed_at + 3_600,
        )


def test_one_matching_signature_among_several_is_a_match() -> None:
    """Stripe sends every valid signature during a secret rotation, and refusing
    a header because one of them is for the other secret breaks the rotation."""
    now = int(time.time())
    payload, headers = signed({"id": "evt_1"}, timestamp=now)
    rotating = headers["stripe-signature"] + ",v1=" + "0" * 64

    assert (
        verify_signature(
            payload=payload,
            signature_header=rotating,
            secret=WEBHOOK_SECRET,
            now=now,
        )["id"]
        == "evt_1"
    )


@pytest.mark.parametrize(
    "header",
    ["", "t=123", "v1=abc", "nonsense", "t=not-a-number,v1=abc"],
    ids=["empty", "no signature", "no timestamp", "malformed", "unparseable timestamp"],
)
def test_a_header_that_is_not_a_signature_is_refused_rather_than_crashing(header: str) -> None:
    with pytest.raises(InvalidSignature):
        verify_signature(payload=b"{}", signature_header=header, secret=WEBHOOK_SECRET)


def test_an_unconfigured_signing_secret_refuses_everything() -> None:
    """The half-configuration that matters: a server that cannot verify must not
    accept, because anything reaching this endpoint credits 额度."""
    now = int(time.time())
    payload, headers = signed({"id": "evt_1"}, timestamp=now)

    with pytest.raises(InvalidSignature):
        verify_signature(
            payload=payload,
            signature_header=headers["stripe-signature"],
            secret="",
            now=now,
        )
