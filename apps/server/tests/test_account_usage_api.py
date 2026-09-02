"""使用记录, one page at a time.

The ledger outlives every 立言任务 in it, so it only grows: an ordinary account
passes a hundred rows well before it passes a hundred 立言任务. What the account
page needs from this endpoint is therefore not "the rows" but "one page of them,
and where that page sits" — which is what these cover.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict, cast
from uuid import uuid4

from database_support import QueueSaying, entitle, migrated_database
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from test_multi_source_intake_api import MemoryObjectStorage
from zhiyan_support import DeterministicJwtVerifier, confirm_sources, zhiyan_client

from liyan_server.account_api import PAGE
from liyan_server.app import create_app
from liyan_server.database import CreditEntry, Database, User
from liyan_server.settings import Settings

HEADERS = {"Authorization": "Bearer allowed-token"}
SECOND = {"Authorization": "Bearer second-token"}


def a_client(tmp_path: Path) -> tuple[TestClient, str]:
    database_url = migrated_database(tmp_path)
    client = TestClient(
        create_app(
            Settings(
                database_url=database_url,
                allowed_emails="writer@example.com,second@example.com",
                signup_grant_credits=0,
            ),
            jwt_verifier=DeterministicJwtVerifier(),
            execution_dispatcher=QueueSaying(True),
            object_storage=MemoryObjectStorage(),
        )
    )
    # The account row exists only once its owner has been seen.
    assert client.get("/account", headers=HEADERS).status_code == 200
    return client, database_url


def fill_ledger(database_url: str, count: int, *, email: str = "writer@example.com") -> None:
    """`count` acts, newest first when read back."""
    database = Database(database_url)
    assert database.engine is not None
    try:
        with Session(database.engine) as session:
            owner = session.query(User).filter_by(email=email).one()
            now = datetime.now(UTC)
            for index in range(count):
                session.add(
                    CreditEntry(
                        owner_id=owner.id,
                        kind="capture",
                        amount=-3,
                        target_type="source_preparation",
                        target_id=uuid4(),
                        created_at=now - timedelta(minutes=index),
                    )
                )
            session.commit()
    finally:
        database.dispose()


class Page(TypedDict):
    """One page of 使用记录 as the account page receives it."""

    entries: list[dict[str, Any]]
    has_more: bool
    total: int
    page_size: int


def usage(
    client: TestClient,
    offset: int = 0,
    headers: dict[str, str] = HEADERS,
) -> Page:
    response = client.get("/account/usage", headers=headers, params={"offset": offset})
    assert response.status_code == 200, response.text
    return cast(Page, response.json())


def test_a_page_carries_at_most_one_page_and_says_how_many_there_are(
    tmp_path: Path,
) -> None:
    client, database_url = a_client(tmp_path)
    fill_ledger(database_url, PAGE * 2 + 5)

    first = usage(client)

    assert len(first["entries"]) == PAGE
    assert first["page_size"] == PAGE
    assert first["total"] == PAGE * 2 + 5
    assert first["has_more"] is True


def test_pages_partition_the_ledger_without_gap_or_repeat(tmp_path: Path) -> None:
    """The property that matters: every row appears exactly once, across pages."""
    client, database_url = a_client(tmp_path)
    total = PAGE * 3 + 7
    fill_ledger(database_url, total)

    seen: list[str] = []
    offset = 0
    while True:
        page = usage(client, offset)
        seen.extend(entry["id"] for entry in page["entries"])
        if not page["has_more"]:
            break
        offset += len(page["entries"])

    assert len(seen) == total
    assert len(set(seen)) == total


def test_the_last_page_holds_the_remainder_and_says_there_is_no_more(
    tmp_path: Path,
) -> None:
    client, database_url = a_client(tmp_path)
    fill_ledger(database_url, PAGE + 3)

    last = usage(client, PAGE)

    assert len(last["entries"]) == 3
    assert last["has_more"] is False
    assert last["total"] == PAGE + 3


def test_newest_first_within_a_page_and_across_them(tmp_path: Path) -> None:
    client, database_url = a_client(tmp_path)
    fill_ledger(database_url, PAGE + 5)

    first = usage(client)
    second = usage(client, PAGE)
    moments = [entry["happened_at"] for entry in first["entries"] + second["entries"]]

    assert moments == sorted(moments, reverse=True)


def test_an_offset_past_the_end_is_an_empty_page_rather_than_a_refusal(
    tmp_path: Path,
) -> None:
    """A client whose ledger shrank under it — a 立言任务 collected — asks for a
    page that no longer exists. An empty page it can render beats a 404 it has
    to interpret."""
    client, database_url = a_client(tmp_path)
    fill_ledger(database_url, 4)

    past_the_end = usage(client, 500)

    assert past_the_end["entries"] == []
    assert past_the_end["has_more"] is False
    assert past_the_end["total"] == 4


def test_a_negative_offset_is_refused(tmp_path: Path) -> None:
    client, _ = a_client(tmp_path)

    assert client.get("/account/usage", headers=HEADERS, params={"offset": -1}).status_code == 422


def test_an_empty_ledger_is_a_page_of_nothing(tmp_path: Path) -> None:
    client, _ = a_client(tmp_path)

    empty = usage(client)

    assert dict(empty) == {"entries": [], "has_more": False, "total": 0, "page_size": PAGE}


def test_the_total_counts_only_this_users_rows(tmp_path: Path) -> None:
    client, database_url = a_client(tmp_path)
    assert client.get("/account", headers=SECOND).status_code == 200
    fill_ledger(database_url, 3)
    fill_ledger(database_url, PAGE + 9, email="second@example.com")

    assert usage(client)["total"] == 3
    assert usage(client, headers=SECOND)["total"] == PAGE + 9


def test_a_结算_is_not_a_row_of_its_own_in_the_total(tmp_path: Path) -> None:
    """使用记录 folds a 结算 into the 预扣 it corrects, so the count must agree
    with the rows — otherwise the last page is announced and comes back short."""
    client, database_url = a_client(tmp_path)
    database = Database(database_url)
    assert database.engine is not None
    try:
        with Session(database.engine) as session:
            owner = session.query(User).filter_by(email="writer@example.com").one()
            target = uuid4()
            now = datetime.now(UTC)
            session.add_all(
                [
                    CreditEntry(
                        owner_id=owner.id,
                        kind="hold",
                        amount=-56,
                        target_type="source_revision",
                        target_id=target,
                        input_version=1,
                        attempt=1,
                        created_at=now,
                    ),
                    CreditEntry(
                        owner_id=owner.id,
                        kind="settle",
                        amount=28,
                        target_type="source_revision",
                        target_id=target,
                        input_version=1,
                        attempt=1,
                        created_at=now,
                    ),
                ]
            )
            session.commit()
    finally:
        database.dispose()

    page = usage(client)

    assert page["total"] == 1
    assert len(page["entries"]) == 1
    # The 预扣 net of its 结算: what the balance actually did.
    assert page["entries"][0]["amount"] == -28


def test_every_metered_act_is_named_in_使用记录(tmp_path: Path) -> None:
    """A row that reads 额度变动 says only that money moved.

    Every act this product charges for has a name the rest of the product uses;
    the ledger uses the same one. 主题提炼 and 主题知言报告 fell through to the
    generic label because they were added to the rate card and not here.
    """
    client, database_url = a_client(tmp_path)
    database = Database(database_url)
    assert database.engine is not None
    try:
        with Session(database.engine) as session:
            owner = session.query(User).filter_by(email="writer@example.com").one()
            now = datetime.now(UTC)
            for index, target_type in enumerate(
                (
                    "source_preparation",
                    "source_revision",
                    "theme_proposal",
                    "theme_revision",
                    "liyan_article",
                )
            ):
                session.add(
                    CreditEntry(
                        owner_id=owner.id,
                        kind="hold",
                        amount=-10,
                        target_type=target_type,
                        target_id=uuid4(),
                        input_version=1,
                        attempt=1,
                        created_at=now - timedelta(minutes=index),
                    )
                )
            session.commit()
    finally:
        database.dispose()

    described = [entry["description"] for entry in usage(client)["entries"]]

    assert described == [
        "来源抓取",
        "知言报告",
        "主题提炼",
        "主题知言报告",
        "立言文章",
    ]
    assert "额度变动" not in described


def test_a_主题知言报告_row_leads_back_to_its_task(tmp_path: Path) -> None:
    client, headers, dispatcher = zhiyan_client(tmp_path)
    entitle(dispatcher.database_url, credits=100_000)
    task_id, _ = confirm_sources(
        client, headers, ["四天工作制已经没有争议"], theme="四天工作制的实际代价"
    )
    dispatcher.run_all()

    rows = client.get("/account/usage", headers=headers).json()["entries"]
    theme_row = next(row for row in rows if row["description"] == "主题知言报告")

    assert theme_row["task_id"] == task_id
    assert theme_row["status"] == "done"
