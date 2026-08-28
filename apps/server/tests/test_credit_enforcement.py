"""What 额度 a 来源 costs, and who is allowed to submit one.

Capture is the only act charged outright: its price is known before it runs, so
there is nothing to estimate and nothing to settle. What these cover is the two
ways that goes wrong — charging one 来源 twice, and letting somebody start work
they cannot pay for.
"""

from pathlib import Path
from uuid import uuid4

from database_support import QueueSaying, entitle, migrated_database
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_multi_source_intake_api import DeterministicJwtVerifier, MemoryObjectStorage
from zhiyan_support import confirm_sources, create_session_sources, zhiyan_client

from liyan_server import credits
from liyan_server.app import create_app
from liyan_server.database import CreditEntry, Database, User
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


def held(database_url: str, kind: str) -> list[int]:
    database = Database(database_url)
    assert database.engine is not None
    try:
        with Session(database.engine) as session:
            return [
                entry.amount
                for entry in session.query(CreditEntry)
                .filter(CreditEntry.kind == kind)
                .order_by(CreditEntry.created_at)
            ]
    finally:
        database.dispose()


def test_a_confirmation_holds_for_every_来源_then_settles_each(tmp_path: Path) -> None:
    """The whole round trip: 预扣 when the 任务版本 is created, 结算 when each run
    ends. The 预扣 is taken inside that transaction, before the Executions it
    pays for exist, which is why it keys to the source Revision."""
    client, headers, dispatcher = zhiyan_client(tmp_path)
    entitle(dispatcher.database_url, credits=100_000)
    confirm_sources(client, headers, ["四天工作制已经没有争议", "碳中和的真实成本"])

    holds = held(dispatcher.database_url, "hold")
    assert len(holds) == 2, "one 预扣 per 来源, taken together"
    assert all(amount < 0 for amount in holds)

    dispatcher.run_all()

    settlements = held(dispatcher.database_url, "settle")
    assert len(settlements) == 2, "one 结算 per run, once each has ended"


def test_a_confirmation_nobody_can_pay_for_is_refused_whole(tmp_path: Path) -> None:
    """Admitting some of the 来源 would leave a 任务版本 with one report and the
    rest nobody will ever analyze — the half-analyzed version the capacity
    ceiling refuses to create, arrived at through the ledger instead of the
    queue. So the 预扣 is checked for the batch, and nothing is held."""
    client, database_url = a_client(tmp_path, grant=CAPTURE_CREDITS + 2)
    ids = create_session_sources(client, HEADERS, ["四天工作制已经没有争议"])

    refused = client.post(
        "/task-creation/confirm",
        headers=HEADERS,
        json={
            "idempotency_key": "key-1",
            "client_session_id": "session-1",
            "source_ids": ids,
        },
    )

    assert refused.status_code == 402, refused.text
    assert held(database_url, "hold") == []
    # The capture fee already paid stands: that work was done.
    assert balance(database_url) == 2


def test_the_account_shows_one_number_and_nothing_that_predicts_it(tmp_path: Path) -> None:
    """A balance and whether URL 来源 are theirs. No estimate: the figure that
    decides whether work begins stays on the server, because a quoted price
    invites arithmetic a settlement will not match."""
    client, _ = a_client(tmp_path)

    account = client.get("/account", headers=HEADERS)

    assert account.status_code == 200
    assert account.json() == {"remaining_credits": 150, "is_paying_user": False}
    assert "estimate" not in account.text


def test_usage_folds_a_结算_into_the_预扣_it_corrects(tmp_path: Path) -> None:
    """A 结算 alone reads as 额度 arriving from nowhere. Against the 预扣 it
    corrects, it explains a number that moved and moved back."""
    client, headers, dispatcher = zhiyan_client(tmp_path)
    entitle(dispatcher.database_url, credits=100_000)
    confirm_sources(client, headers, ["四天工作制已经没有争议"])

    running = client.get("/account/usage", headers=headers).json()["entries"]
    analysis = next(row for row in running if row["kind"] == "hold")
    assert analysis["status"] == "running"
    assert analysis["held"] == -analysis["amount"], "committed in full while it runs"

    dispatcher.run_all()

    settled = client.get("/account/usage", headers=headers).json()["entries"]
    analysis = next(row for row in settled if row["kind"] == "hold")
    assert analysis["status"] in {"done", "failed"}
    assert analysis["held"] is not None
    assert "分析来源" in analysis["description"]


def test_usage_still_reads_after_the_task_it_refers_to_is_gone(tmp_path: Path) -> None:
    """cleanup removes 立言任务 and cascades into their 来源; these rows are kept
    on purpose. A 使用记录 older than a deleted task still has to say something."""
    client, database_url = a_client(tmp_path)
    entitle(database_url, credits=1_000)
    database = Database(database_url)
    assert database.engine is not None
    try:
        with Session(database.engine) as session:
            user = session.query(User).one()
            credits.hold(
                session,
                user.id,
                target_type="source_revision",
                target_id=uuid4(),
                attempt=1,
                credits=56,
            )
            session.commit()
    finally:
        database.dispose()

    rows = client.get("/account/usage", headers=HEADERS).json()["entries"]

    assert rows[0]["description"] == "分析来源"
