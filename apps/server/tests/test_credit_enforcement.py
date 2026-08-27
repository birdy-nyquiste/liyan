"""What 额度 a 来源 costs, and who is allowed to submit one.

Capture is the only act charged outright: its price is known before it runs, so
there is nothing to estimate and nothing to settle. What these cover is the two
ways that goes wrong — charging one 来源 twice, and letting somebody start work
they cannot pay for.
"""

from pathlib import Path

from database_support import QueueSaying, entitle, migrated_database
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_multi_source_intake_api import DeterministicJwtVerifier, MemoryObjectStorage

from liyan_server import credits
from liyan_server.app import create_app
from liyan_server.database import Database, User
from liyan_server.rate_card import CAPTURE_CREDITS
from liyan_server.settings import Settings

HEADERS = {"Authorization": "Bearer allowed-token"}


def a_client(tmp_path: Path, *, grant: int = 150) -> tuple[TestClient, str]:
    database_url = migrated_database(tmp_path)
    client = TestClient(
        create_app(
            Settings(
                database_url=database_url,
                allowed_emails="writer@example.com",
                signup_grant_credits=grant,
            ),
            jwt_verifier=DeterministicJwtVerifier(),
            execution_dispatcher=QueueSaying(True),
            object_storage=MemoryObjectStorage(),
        )
    )
    return client, database_url


def balance(database_url: str) -> int:
    database = Database(database_url)
    assert database.engine is not None
    try:
        with Session(database.engine) as session:
            user = session.query(User).one()
            return credits.remaining(session, user.id)
    finally:
        database.dispose()


def paste(client: TestClient, source_id: str) -> object:
    return client.post(
        "/task-creation/pasted-sources",
        headers=HEADERS,
        json={
            "client_session_id": "session-1",
            "client_source_id": source_id,
            "title": f"四天工作制 {source_id}",
            "body": "英国2022年的四天工作制试验覆盖了61家公司。" * 20,
            "provenance": "https://press.example/story",
        },
    )


def test_a_new_user_is_given_their_额度_with_the_row_that_creates_them(tmp_path: Path) -> None:
    """In the same transaction as the user. One who existed for even a moment
    without their 赠送额度 could be refused their first 来源, and nothing would
    ever come back to give it to them."""
    client, database_url = a_client(tmp_path)

    assert client.get("/auth/me", headers=HEADERS).status_code == 200

    assert balance(database_url) == 150


def test_a_pasted_来源_costs_the_flat_capture_fee(tmp_path: Path) -> None:
    client, database_url = a_client(tmp_path)

    assert paste(client, "source-1").status_code == 201  # type: ignore[attr-defined]

    assert balance(database_url) == 150 - CAPTURE_CREDITS


def test_a_user_who_cannot_afford_a_来源_is_told_so_and_not_charged(tmp_path: Path) -> None:
    """402 rather than 429: this is not a queue to wait out, and the remedy is
    a purchase. No figure is quoted — the estimate answers whether work begins,
    and a quoted price invites arithmetic that a settlement will not match."""
    client, database_url = a_client(tmp_path, grant=2)

    refused = paste(client, "source-1")

    assert refused.status_code == 402  # type: ignore[attr-defined]
    assert "额度不足" in refused.json()["detail"]  # type: ignore[attr-defined]
    assert balance(database_url) == 2


def test_url_来源_belong_to_a_付费用户(tmp_path: Path) -> None:
    """A grant is not a purchase. The workbench shows these locked rather than
    hidden, so reaching this is a client going around the interface."""
    client, database_url = a_client(tmp_path)

    refused = client.post(
        "/task-creation/url-sources",
        headers=HEADERS,
        json={
            "client_session_id": "session-1",
            "client_source_id": "source-1",
            "url": "https://example.com/story",
        },
    )

    assert refused.status_code == 402
    assert "购买额度后解锁" in refused.json()["detail"]
    assert balance(database_url) == 150


def test_a_付费用户_may_submit_a_url_来源(tmp_path: Path) -> None:
    client, database_url = a_client(tmp_path)
    entitle(database_url, credits=1_000)

    created = client.post(
        "/task-creation/url-sources",
        headers=HEADERS,
        json={
            "client_session_id": "session-1",
            "client_source_id": "source-1",
            "url": "https://example.com/story",
        },
    )

    assert created.status_code == 201, created.text
    assert balance(database_url) == 1_000 - CAPTURE_CREDITS
