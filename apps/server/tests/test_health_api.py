import pytest
from fastapi.testclient import TestClient

from liyan_server.app import create_app
from liyan_server.settings import Settings


def client_for(database_url: str) -> TestClient:
    return TestClient(create_app(Settings(database_url=database_url)))


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
        "checks": {"database": "available"},
    }


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
        "checks": {"database": "unavailable"},
    }
