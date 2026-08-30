from typing import Any, BinaryIO

import pytest
from database_support import QueueSaying
from fastapi.testclient import TestClient

from liyan_server.app import create_app
from liyan_server.object_storage import ObjectStorage, ObjectStorageState, StoredObject
from liyan_server.settings import Settings


def configured(database_url: str) -> Settings:
    """Settings whose storage is fully configured, so only the double decides.

    Stripe is blanked explicitly rather than left to default. `Settings` reads
    the developer's own `.env`, so a machine with real keys in it would make
    these tests report `billing: "configured"` and fail — a suite that passes
    or fails on what somebody happens to have locally, which is the thing
    `.env.e2e` exists to argue against.
    """
    return Settings(
        database_url=database_url,
        r2_endpoint_url="https://account.r2.cloudflarestorage.com",
        r2_access_key_id="key-id",
        r2_secret_access_key="secret",
        r2_bucket="liyan-local",
        stripe_secret_key="",
        stripe_webhook_secret="",
        stripe_credit_packs="",
    )


class StorageSaying(ObjectStorage):
    """Storage that reports a state without any of it being real."""

    def __init__(self, state: ObjectStorageState) -> None:
        self._state = state

    def put(self, key: str, stream: BinaryIO, *, content_type: str) -> None: ...

    def open(self, key: str) -> BinaryIO:  # pragma: no cover - never read here
        raise NotImplementedError

    def delete(self, key: str) -> None: ...

    def list_objects(  # pragma: no cover - readiness never lists
        self, prefix: str = ""
    ) -> tuple[StoredObject, ...]:
        raise NotImplementedError

    def state(self) -> ObjectStorageState:
        return self._state


def client_for(
    database_url: str,
    storage: ObjectStorage | None = None,
    *,
    queue_reachable: bool = True,
) -> TestClient:
    return TestClient(
        create_app(
            configured(database_url),
            object_storage=storage or StorageSaying("ready"),
            execution_dispatcher=QueueSaying(queue_reachable),
        )
    )


def test_liveness_reports_that_the_server_process_is_alive() -> None:
    client = client_for("sqlite+pysqlite:///:memory:")

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_reports_when_required_dependencies_are_usable() -> None:
    client = client_for("sqlite+pysqlite:///:memory:")

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "database": "available",
            "queue": "available",
            "worker": "unknown",
            "object_storage": "ready",
            "billing": "unconfigured",
        },
    }


@pytest.mark.parametrize(
    "state", ["unconfigured", "unreachable"], ids=["unconfigured", "unreachable"]
)
def test_readiness_names_the_state_of_object_storage_beside_the_database(
    state: ObjectStorageState,
) -> None:
    client = client_for("sqlite+pysqlite:///:memory:", StorageSaying(state))

    response = client.get("/health/ready")

    # A deployment that cannot take uploads still reads and writes everything
    # else, and the Technical Spec forbids making a short R2 outage a restart
    # condition — so this is reported, not gated.
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"]["object_storage"] == state


def test_an_unconfigured_bucket_is_never_mistaken_for_an_outage() -> None:
    unconfigured = client_for("sqlite+pysqlite:///:memory:", StorageSaying("unconfigured"))
    unreachable = client_for("sqlite+pysqlite:///:memory:", StorageSaying("unreachable"))

    assert unconfigured.get("/health/ready").json()["checks"]["object_storage"] != (
        unreachable.get("/health/ready").json()["checks"]["object_storage"]
    )


def test_a_deployment_that_cannot_sell_额度_is_still_ready() -> None:
    """Reported, never gating. Everything a user already holds still spends, and
    taking the API out of rotation would turn a missing feature into an outage."""
    client = client_for("sqlite+pysqlite:///:memory:")

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["checks"]["billing"] == "unconfigured"


def test_billing_reports_configured_only_when_it_could_actually_fulfill() -> None:
    """A secret key without a signing secret is the dangerous half: Checkout
    opens, and nothing ever credits. That is not most of the way configured."""
    settings = configured("sqlite+pysqlite:///:memory:")
    half = settings.model_copy(
        update={
            "stripe_secret_key": "sk_test_x",
            "stripe_credit_packs": '[{"price_id": "price_x", "credits": 2000}]',
        }
    )
    whole = half.model_copy(update={"stripe_webhook_secret": "whsec_x"})

    assert _readiness(half)["checks"]["billing"] == "unconfigured"
    assert _readiness(whole)["checks"]["billing"] == "configured"


def _readiness(settings: Settings) -> Any:
    client = TestClient(
        create_app(
            settings,
            object_storage=StorageSaying("ready"),
            execution_dispatcher=QueueSaying(True),
        )
    )
    return dict(client.get("/health/ready").json())


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite+pysqlite:////a-directory-that-does-not-exist/liyan.db",
        "unknown://database",
    ],
    ids=["unreachable", "misconfigured"],
)
def test_readiness_is_unavailable_when_the_database_cannot_be_used(database_url: str) -> None:
    client = client_for(database_url)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {
            "database": "unavailable",
            "queue": "available",
            "worker": "unknown",
            "object_storage": "ready",
            "billing": "unconfigured",
        },
    }
