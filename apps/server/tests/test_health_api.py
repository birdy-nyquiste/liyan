from typing import BinaryIO

import pytest
from fastapi.testclient import TestClient

from liyan_server.app import create_app
from liyan_server.object_storage import ObjectStorage, ObjectStorageState, StoredObject
from liyan_server.settings import Settings


def configured(database_url: str) -> Settings:
    """Settings whose storage is fully configured, so only the double decides."""
    return Settings(
        database_url=database_url,
        r2_endpoint_url="https://account.r2.cloudflarestorage.com",
        r2_access_key_id="key-id",
        r2_secret_access_key="secret",
        r2_bucket="liyan-local",
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
    database_url: str, storage: ObjectStorage | None = None
) -> TestClient:
    return TestClient(
        create_app(
            configured(database_url),
            object_storage=storage or StorageSaying("ready"),
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
        "checks": {"database": "available", "object_storage": "ready"},
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
        "checks": {"database": "unavailable", "object_storage": "ready"},
    }
