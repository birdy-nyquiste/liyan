"""A real Cloudflare R2 round-trip, run only when explicitly asked for.

Opt-in by design: the deterministic suite must stay offline, and this one writes
to a real bucket. Enable it with `LIYAN_LIVE_R2=1` against a bucket you are
willing to have an object created in and deleted from.

    LIYAN_LIVE_R2=1 .venv/bin/python -m pytest apps/server/tests/test_r2_live_contract.py

It exists because the in-memory double cannot tell you that credentials, the
endpoint, and the bucket name actually agree with each other — the failure this
whole area is about.
"""

import os
import uuid
from collections.abc import Iterator
from contextlib import suppress
from io import BytesIO

import pytest

from liyan_server.object_storage import R2ObjectStorage
from liyan_server.settings import Settings

pytestmark = pytest.mark.skipif(
    os.environ.get("LIYAN_LIVE_R2") != "1",
    reason="Set LIYAN_LIVE_R2=1 to run the live R2 contract check.",
)

PAYLOAD = "# liyan R2 contract check\n\n真实往返，用完即删。\n".encode()


@pytest.fixture
def storage() -> R2ObjectStorage:
    configured = R2ObjectStorage(Settings())
    missing = configured.missing_settings()
    assert not missing, f"LIYAN_LIVE_R2 is set but {', '.join(missing)} is empty."
    return configured


@pytest.fixture
def key(storage: R2ObjectStorage) -> Iterator[str]:
    #: Namespaced and unique so a run can never collide with real content.
    object_key = f"liyan-live-contract/{uuid.uuid4()}.md"
    try:
        yield object_key
    finally:
        # Cleanup must never mask the failure the test was reporting.
        with suppress(Exception):
            storage.delete(object_key)


def test_a_configured_bucket_reports_itself_ready(storage: R2ObjectStorage) -> None:
    assert storage.state() == "ready"


def test_an_object_survives_a_put_and_comes_back_byte_for_byte(
    storage: R2ObjectStorage, key: str
) -> None:
    storage.put(key, BytesIO(PAYLOAD), content_type="text/markdown")

    assert storage.open(key).read() == PAYLOAD


def test_a_deleted_object_is_really_gone(storage: R2ObjectStorage, key: str) -> None:
    storage.put(key, BytesIO(PAYLOAD), content_type="text/markdown")
    storage.delete(key)

    with pytest.raises(Exception):  # noqa: B017 - botocore's error type is not ours
        storage.open(key)


def test_a_wrong_secret_is_an_outage_rather_than_a_gap_in_configuration() -> None:
    settings = Settings()
    wrong = R2ObjectStorage(
        Settings(
            r2_endpoint_url=settings.r2_endpoint_url,
            r2_access_key_id=settings.r2_access_key_id,
            r2_secret_access_key="0" * 40,
            r2_bucket=settings.r2_bucket,
        )
    )

    # Everything is filled in, so this is not "unconfigured" — the operator has
    # done their part and the answer has to point at the credential instead.
    assert wrong.missing_settings() == ()
    assert wrong.state() == "unreachable"
