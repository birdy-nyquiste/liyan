"""Telling an unconfigured bucket apart from an unreachable one."""

import pytest

from liyan_server.object_storage import (
    ObjectStorageUnconfigured,
    R2ObjectStorage,
)
from liyan_server.settings import Settings

ENDPOINT = "https://account.r2.cloudflarestorage.com"
SETTING_NAMES = (
    "r2_endpoint_url",
    "r2_access_key_id",
    "r2_secret_access_key",
    "r2_bucket",
)


def configured(**overrides: str) -> Settings:
    """A fully configured R2, with named settings blanked or replaced."""
    values = {
        "r2_endpoint_url": ENDPOINT,
        "r2_access_key_id": "key-id",
        "r2_secret_access_key": "secret",
        "r2_bucket": "liyan-local",
    } | overrides
    return Settings(
        r2_endpoint_url=values["r2_endpoint_url"],
        r2_access_key_id=values["r2_access_key_id"],
        r2_secret_access_key=values["r2_secret_access_key"],
        r2_bucket=values["r2_bucket"],
    )


def test_a_fresh_environment_names_every_setting_an_operator_still_owes() -> None:
    storage = R2ObjectStorage(
        configured(
            r2_endpoint_url="", r2_access_key_id="", r2_secret_access_key="", r2_bucket=""
        )
    )

    assert storage.missing_settings() == (
        "LIYAN_R2_ENDPOINT_URL",
        "LIYAN_R2_ACCESS_KEY_ID",
        "LIYAN_R2_SECRET_ACCESS_KEY",
        "LIYAN_R2_BUCKET",
    )


@pytest.mark.parametrize("blank", SETTING_NAMES)
def test_one_missing_setting_is_enough_to_be_unconfigured(blank: str) -> None:
    storage = R2ObjectStorage(configured(**{blank: ""}))

    assert storage.missing_settings()
    # Answered without a network call, so a half-configured bucket is never
    # reported as an outage.
    assert storage.state() == "unconfigured"


def test_whitespace_is_not_configuration() -> None:
    storage = R2ObjectStorage(configured(r2_bucket="   "))

    assert storage.missing_settings() == ("LIYAN_R2_BUCKET",)


def test_a_fully_configured_bucket_owes_nothing() -> None:
    storage = R2ObjectStorage(configured())

    assert storage.missing_settings() == ()


def test_configured_but_absent_storage_reads_as_unreachable() -> None:
    storage = R2ObjectStorage(configured(r2_endpoint_url="http://127.0.0.1:1"))

    # Nothing is listening on that port, which is an outage rather than a gap
    # in configuration — the distinction the whole ticket turns on.
    assert storage.state() == "unreachable"


def test_an_upload_against_nothing_says_so_rather_than_failing_obscurely() -> None:
    storage = R2ObjectStorage(configured(r2_bucket=""))

    with pytest.raises(ObjectStorageUnconfigured) as unconfigured:
        storage.delete("any-key")

    assert "LIYAN_R2_BUCKET" in str(unconfigured.value)
