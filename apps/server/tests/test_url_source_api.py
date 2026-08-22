import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient

from liyan_server.app import create_app
from liyan_server.auth import InvalidAccessToken, VerifiedIdentity
from liyan_server.settings import Settings
from liyan_server.url_fetch_worker import (
    UrlExtraction,
    UrlFetcher,
    UrlFetchFailure,
    process_url_fetch,
)


class DeterministicJwtVerifier:
    def verify(self, token: str) -> VerifiedIdentity:
        identities = {
            "allowed-token": VerifiedIdentity(
                subject="supabase-user-1", email="writer@example.com"
            ),
            "second-token": VerifiedIdentity(
                subject="supabase-user-2", email="second@example.com"
            ),
        }
        try:
            return identities[token]
        except KeyError as error:
            raise InvalidAccessToken from error


class DeterministicUrlFetcher:
    def __init__(self) -> None:
        self.outcomes: list[UrlExtraction | UrlFetchFailure] = []

    def fetch(self, url: str) -> UrlExtraction:
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, UrlFetchFailure):
                raise outcome
            return outcome
        return UrlExtraction(
            title="  Extracted   title ",
            body="  First paragraph.\r\n\r\n" + ("Full article body. " * 40) + " ",
            metadata={"author": "Example Author"},
        )


class RecordingExecutionDispatcher:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.execution_ids: list[UUID] = []
        self.deterministic_fetcher = DeterministicUrlFetcher()
        self.fetcher: UrlFetcher = self.deterministic_fetcher

    def dispatch(self, execution_id: UUID) -> None:
        self.execution_ids.append(execution_id)

    def run_next(self) -> None:
        process_url_fetch(
            self.database_url,
            self.execution_ids.pop(0),
            self.fetcher,
            short_source_characters=500,
        )


class FailingExecutionDispatcher(RecordingExecutionDispatcher):
    def dispatch(self, execution_id: UUID) -> None:
        raise RuntimeError("broker unavailable")


def migrated_database(tmp_path: Path) -> str:
    project_root = Path(__file__).resolve().parents[3]
    database_url = f"sqlite+pysqlite:///{tmp_path / 'liyan.db'}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=project_root,
        env=os.environ | {"LIYAN_DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return database_url


def authenticated_client(
    tmp_path: Path,
) -> tuple[TestClient, dict[str, str], RecordingExecutionDispatcher]:
    database_url = migrated_database(tmp_path)
    dispatcher = RecordingExecutionDispatcher(database_url)
    settings = Settings(
        database_url=database_url,
        allowed_emails="writer@example.com",
    )
    client = TestClient(
        create_app(
            settings,
            jwt_verifier=DeterministicJwtVerifier(),
            execution_dispatcher=dispatcher,
        )
    )
    return client, {"Authorization": "Bearer allowed-token"}, dispatcher


def test_submitting_a_supported_url_creates_one_durable_fetch_execution(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = authenticated_client(tmp_path)

    response = client.post(
        "/task-creation/url-sources",
        headers=headers,
        json={
            "client_session_id": "session-1",
            "client_source_id": "source-1",
            "url": " HTTPS://Example.COM:443/article?id=1#comments ",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["client_session_id"] == "session-1"
    assert body["client_source_id"] == "source-1"
    assert body["input_url"] == "HTTPS://Example.COM:443/article?id=1#comments"
    assert body["normalized_url"] == "https://example.com/article?id=1"
    assert body["input_version"] == 1
    assert body["status"] == "processing"
    assert body["title"] is None
    assert body["body"] is None
    assert body["warnings"] == []
    assert body["failure"] is None
    assert body["capabilities"] == {
        "can_retry": False,
        "can_replace": False,
        "can_cancel": True,
    }
    execution = body["active_execution"]
    assert execution["operation"] == "fetch_url"
    assert execution["status"] == "queued"
    assert execution["attempt"] == 1
    assert execution["input_version"] == 1
    assert execution["started_at"] is None
    assert execution["finished_at"] is None
    assert execution["result_id"] is None
    assert execution["error"] is None
    assert dispatcher.execution_ids == [UUID(execution["id"])]


def test_private_network_url_is_rejected_before_dispatch(tmp_path: Path) -> None:
    client, headers, dispatcher = authenticated_client(tmp_path)

    response = client.post(
        "/task-creation/url-sources",
        headers=headers,
        json={
            "client_session_id": "session-1",
            "client_source_id": "source-1",
            "url": "http://127.0.0.1/internal",
        },
    )

    assert response.status_code == 422
    assert dispatcher.execution_ids == []


def test_dispatch_failure_becomes_an_actionable_source_failure(tmp_path: Path) -> None:
    database_url = migrated_database(tmp_path)
    dispatcher = FailingExecutionDispatcher(database_url)
    client = TestClient(
        create_app(
            Settings(database_url=database_url, allowed_emails="writer@example.com"),
            jwt_verifier=DeterministicJwtVerifier(),
            execution_dispatcher=dispatcher,
        )
    )

    response = client.post(
        "/task-creation/url-sources",
        headers={"Authorization": "Bearer allowed-token"},
        json={
            "client_session_id": "session-1",
            "client_source_id": "source-1",
            "url": "https://example.com/article",
        },
    )

    assert response.status_code == 201
    source = response.json()
    assert source["status"] == "failure"
    assert source["failure"]["code"] == "dispatch_failed"
    assert source["active_execution"]["status"] == "failed"
    assert source["capabilities"]["can_retry"] is True


def test_failed_url_source_retries_independently_without_discarding_ready_input(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = authenticated_client(tmp_path)
    ready_source = client.post(
        "/task-creation/url-sources",
        headers=headers,
        json={
            "client_session_id": "session-1",
            "client_source_id": "ready-source",
            "url": "https://example.com/ready",
        },
    ).json()
    dispatcher.run_next()
    failed_source = client.post(
        "/task-creation/url-sources",
        headers=headers,
        json={
            "client_session_id": "session-1",
            "client_source_id": "failed-source",
            "url": "https://example.com/unavailable",
        },
    ).json()
    dispatcher.deterministic_fetcher.outcomes.append(
        UrlFetchFailure(
            "inaccessible_url",
            "The article is not publicly accessible. Replace this source or try another URL.",
        )
    )
    dispatcher.run_next()

    failed = client.get(
        f"/task-creation/url-sources/{failed_source['id']}", headers=headers
    ).json()
    assert failed["status"] == "failure"
    assert failed["failure"] == {
        "code": "inaccessible_url",
        "message": (
            "The article is not publicly accessible. Replace this source or try another URL."
        ),
    }
    assert failed["active_execution"]["status"] == "failed"
    assert failed["active_execution"]["error"] == failed["failure"]
    assert failed["capabilities"]["can_retry"] is True

    retried = client.post(
        f"/task-creation/url-sources/{failed_source['id']}/retry", headers=headers
    )
    assert retried.status_code == 202
    assert retried.json()["status"] == "processing"
    assert retried.json()["active_execution"]["attempt"] == 2
    dispatcher.run_next()

    assert client.get(
        f"/task-creation/url-sources/{failed_source['id']}", headers=headers
    ).json()["status"] == "ready"
    preserved = client.get(
        f"/task-creation/url-sources/{ready_source['id']}", headers=headers
    ).json()
    assert preserved["status"] == "ready"
    assert preserved["active_execution"]["attempt"] == 1


def test_worker_result_becomes_editable_ready_content_with_execution_trace(tmp_path: Path) -> None:
    client, headers, dispatcher = authenticated_client(tmp_path)
    created = client.post(
        "/task-creation/url-sources",
        headers=headers,
        json={
            "client_session_id": "session-1",
            "client_source_id": "source-1",
            "url": "https://example.com/article?id=1",
        },
    ).json()

    dispatcher.run_next()
    response = client.get(f"/task-creation/url-sources/{created['id']}", headers=headers)

    assert response.status_code == 200
    source = response.json()
    assert source["status"] == "ready"
    assert source["title"] == "Extracted title"
    assert source["body"].startswith("First paragraph.\n\nFull article body.")
    assert source["provenance"] == "https://example.com/article?id=1"
    assert source["warnings"] == []
    assert source["failure"] is None
    assert source["capabilities"] == {
        "can_retry": False,
        "can_replace": True,
        "can_cancel": False,
    }
    execution = source["active_execution"]
    assert execution["status"] == "succeeded"
    assert execution["started_at"] is not None
    assert execution["finished_at"] is not None
    assert execution["result_id"] is not None
    assert execution["error"] is None


def test_missing_title_and_short_extraction_are_visible_non_blocking_warnings(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = authenticated_client(tmp_path)
    dispatcher.deterministic_fetcher.outcomes.append(
        UrlExtraction(title=None, body="Short extracted body.", metadata={})
    )
    created = client.post(
        "/task-creation/url-sources",
        headers=headers,
        json={
            "client_session_id": "session-1",
            "client_source_id": "source-1",
            "url": "https://example.com/article",
        },
    ).json()

    dispatcher.run_next()
    source = client.get(
        f"/task-creation/url-sources/{created['id']}", headers=headers
    ).json()

    assert source["status"] == "warning"
    assert source["title"] == "example.com"
    assert source["body"] == "Short extracted body."
    assert [warning["code"] for warning in source["warnings"]] == [
        "missing_title",
        "short_body",
    ]
    assert source["capabilities"]["can_retry"] is False


def test_ready_url_source_content_is_editable_before_confirmation(tmp_path: Path) -> None:
    client, headers, dispatcher = authenticated_client(tmp_path)
    created = client.post(
        "/task-creation/url-sources",
        headers=headers,
        json={
            "client_session_id": "session-1",
            "client_source_id": "source-1",
            "url": "https://example.com/article?id=1",
        },
    ).json()
    dispatcher.run_next()

    response = client.patch(
        f"/task-creation/url-sources/{created['id']}/content",
        headers=headers,
        json={
            "title": "  My   accepted title ",
            "body": "  My accepted body.  ",
            "provenance": "   ",
        },
    )

    assert response.status_code == 200
    source = response.json()
    assert source["status"] == "warning"
    assert source["input_version"] == 2
    assert source["title"] == "My accepted title"
    assert source["body"] == "My accepted body."
    assert source["provenance"] is None
    assert [warning["code"] for warning in source["warnings"]] == [
        "short_body",
        "missing_provenance",
    ]
    assert source["active_execution"]["status"] == "succeeded"


def test_running_url_must_be_cancelled_before_it_can_be_replaced(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = authenticated_client(tmp_path)
    created = client.post(
        "/task-creation/url-sources",
        headers=headers,
        json={
            "client_session_id": "session-1",
            "client_source_id": "source-1",
            "url": "https://example.com/old",
        },
    ).json()
    old_execution_id = created["active_execution"]["id"]

    class CancellingFetcher:
        def fetch(self, url: str) -> UrlExtraction:
            assert url == "https://example.com/old"
            replaced = client.put(
                f"/task-creation/url-sources/{created['id']}",
                headers=headers,
                json={"url": "https://example.com/new"},
            )
            assert replaced.status_code == 409
            cancelled = client.post(f"/executions/{old_execution_id}/cancel", headers=headers)
            assert cancelled.status_code == 202
            assert cancelled.json()["status"] == "cancel_requested"
            return UrlExtraction(
                title="Late old title",
                body="Late old body that must never be accepted.",
                metadata={},
            )

    dispatcher.fetcher = CancellingFetcher()
    dispatcher.run_next()

    source = client.get(
        f"/task-creation/url-sources/{created['id']}", headers=headers
    ).json()
    assert source["input_version"] == 1
    assert source["normalized_url"] == "https://example.com/old"
    assert source["status"] == "failure"
    assert source["title"] is None
    assert source["body"] is None
    old_execution = client.get(f"/executions/{old_execution_id}", headers=headers).json()
    assert old_execution["status"] == "cancelled"
    assert old_execution["cancellation_requested_at"] is not None
    assert old_execution["result_id"] is not None

    replaced = client.put(
        f"/task-creation/url-sources/{created['id']}",
        headers=headers,
        json={"url": "https://example.com/new"},
    )
    assert replaced.status_code == 202
    assert replaced.json()["input_version"] == 2
    dispatcher.fetcher = DeterministicUrlFetcher()
    dispatcher.run_next()
    accepted = client.get(
        f"/task-creation/url-sources/{created['id']}", headers=headers
    ).json()
    assert accepted["status"] == "ready"
    assert accepted["title"] == "Extracted title"
    assert accepted["provenance"] == "https://example.com/new"


def test_cancelling_a_running_fetch_prevents_late_result_acceptance(tmp_path: Path) -> None:
    client, headers, dispatcher = authenticated_client(tmp_path)
    created = client.post(
        "/task-creation/url-sources",
        headers=headers,
        json={
            "client_session_id": "session-1",
            "client_source_id": "source-1",
            "url": "https://example.com/article",
        },
    ).json()
    execution_id = created["active_execution"]["id"]

    class CancellingFetcher:
        def fetch(self, url: str) -> UrlExtraction:
            cancelled = client.post(f"/executions/{execution_id}/cancel", headers=headers)
            assert cancelled.status_code == 202
            assert cancelled.json()["status"] == "cancel_requested"
            return UrlExtraction(
                title="Late title",
                body="Late body that must remain trace-only.",
                metadata={},
            )

    dispatcher.fetcher = CancellingFetcher()
    dispatcher.run_next()

    source = client.get(
        f"/task-creation/url-sources/{created['id']}", headers=headers
    ).json()
    assert source["status"] == "failure"
    assert source["failure"] == {
        "code": "cancelled",
        "message": "Fetching was cancelled. Retry it or replace this source.",
    }
    assert source["title"] is None
    assert source["body"] is None
    execution = client.get(f"/executions/{execution_id}", headers=headers).json()
    assert execution["status"] == "cancelled"
    assert execution["result_id"] is not None
    assert execution["cancellation_requested_at"] is not None


def test_failure_returned_after_cancellation_remains_cancelled(tmp_path: Path) -> None:
    client, headers, dispatcher = authenticated_client(tmp_path)
    created = client.post(
        "/task-creation/url-sources",
        headers=headers,
        json={
            "client_session_id": "session-1",
            "client_source_id": "source-1",
            "url": "https://example.com/article",
        },
    ).json()
    execution_id = created["active_execution"]["id"]

    class CancellingFailureFetcher:
        def fetch(self, url: str) -> UrlExtraction:
            cancelled = client.post(f"/executions/{execution_id}/cancel", headers=headers)
            assert cancelled.status_code == 202
            raise UrlFetchFailure("inaccessible_url", "Provider failed after cancellation.")

    dispatcher.fetcher = CancellingFailureFetcher()
    dispatcher.run_next()

    source = client.get(
        f"/task-creation/url-sources/{created['id']}", headers=headers
    ).json()
    assert source["status"] == "failure"
    assert source["failure"]["code"] == "cancelled"
    execution = client.get(f"/executions/{execution_id}", headers=headers).json()
    assert execution["status"] == "cancelled"
    assert execution["error"] == {
        "code": "inaccessible_url",
        "message": "Provider failed after cancellation.",
    }


def test_url_source_and_execution_are_owner_isolated(tmp_path: Path) -> None:
    database_url = migrated_database(tmp_path)
    dispatcher = RecordingExecutionDispatcher(database_url)
    client = TestClient(
        create_app(
            Settings(
                database_url=database_url,
                allowed_emails="writer@example.com,second@example.com",
            ),
            jwt_verifier=DeterministicJwtVerifier(),
            execution_dispatcher=dispatcher,
        )
    )
    first_headers = {"Authorization": "Bearer allowed-token"}
    second_headers = {"Authorization": "Bearer second-token"}
    created = client.post(
        "/task-creation/url-sources",
        headers=first_headers,
        json={
            "client_session_id": "session-1",
            "client_source_id": "source-1",
            "url": "https://example.com/article",
        },
    ).json()

    assert client.get(
        f"/task-creation/url-sources/{created['id']}", headers=second_headers
    ).status_code == 404
    assert client.get(
        f"/executions/{created['active_execution']['id']}", headers=second_headers
    ).status_code == 404
    assert client.post(
        f"/executions/{created['active_execution']['id']}/cancel", headers=second_headers
    ).status_code == 404
