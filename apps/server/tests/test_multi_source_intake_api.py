from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, cast
from uuid import UUID

from database_support import entitle, migrated_database
from fastapi.testclient import TestClient

from liyan_server.app import create_app
from liyan_server.auth import InvalidAccessToken, VerifiedIdentity
from liyan_server.file_parse_worker import process_file_parse
from liyan_server.file_parsing import FileParseLimits
from liyan_server.object_storage import ObjectStorage, StoredObject
from liyan_server.settings import Settings
from liyan_server.url_fetch_worker import UrlExtraction, process_url_fetch


class DeterministicJwtVerifier:
    def verify(self, token: str) -> VerifiedIdentity:
        if token == "allowed-token":
            return VerifiedIdentity(
                subject="supabase-user-1",
                email="writer@example.com",
            )
        raise InvalidAccessToken


class MemoryObjectStorage(ObjectStorage):
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, stream: BinaryIO, *, content_type: str) -> None:
        self.objects[key] = stream.read()

    def open(self, key: str) -> BinaryIO:
        return BytesIO(self.objects[key])

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def list_objects(self, prefix: str = "") -> tuple[StoredObject, ...]:
        return tuple(
            StoredObject(key=key, written_at=datetime.now(UTC))
            for key in sorted(self.objects)
            if key.startswith(prefix)
        )


class DeterministicUrlFetcher:
    def fetch(self, url: str) -> UrlExtraction:
        return UrlExtraction(
            title="Fetched article",
            body="Complete extracted article body. " * 30,
            metadata={},
        )


class RecordingExecutionDispatcher:
    def __init__(self, database_url: str, storage: ObjectStorage) -> None:
        self.database_url = database_url
        self.storage = storage
        self.execution_ids: list[UUID] = []

    def dispatch(self, execution_id: UUID) -> None:
        self.execution_ids.append(execution_id)

    def is_reachable(self) -> bool:
        return True

    def run_url(self) -> None:
        process_url_fetch(
            self.database_url,
            self.execution_ids.pop(0),
            DeterministicUrlFetcher(),
            short_source_characters=500,
        )

    def run_file(self) -> None:
        process_file_parse(
            self.database_url,
            self.execution_ids.pop(0),
            self.storage,
            limits=FileParseLimits(
                max_pages=20,
                max_normalized_characters=10_000,
                timeout_seconds=10,
                max_docx_entries=100,
                max_docx_uncompressed_bytes=1_000_000,
            ),
            short_source_characters=500,
        )


def authenticated_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    settings = Settings(
        database_url=_entitled(tmp_path),
        allowed_emails="writer@example.com",
    )
    client = TestClient(create_app(settings, jwt_verifier=DeterministicJwtVerifier()))
    return client, {"Authorization": "Bearer allowed-token"}


def mixed_client(
    tmp_path: Path,
) -> tuple[TestClient, dict[str, str], RecordingExecutionDispatcher]:
    database_url = migrated_database(tmp_path)
    entitle(database_url)
    storage = MemoryObjectStorage()
    dispatcher = RecordingExecutionDispatcher(database_url, storage)
    settings = Settings(
        database_url=database_url,
        allowed_emails="writer@example.com",
    )
    client = TestClient(
        create_app(
            settings,
            jwt_verifier=DeterministicJwtVerifier(),
            execution_dispatcher=dispatcher,
            object_storage=storage,
        )
    )
    return client, {"Authorization": "Bearer allowed-token"}, dispatcher


def add_pasted_source(
    client: TestClient,
    headers: dict[str, str],
    *,
    client_source_id: str,
    title: str,
    body: str,
    provenance: str | None = None,
) -> dict[str, object]:
    response = client.post(
        "/task-creation/pasted-sources",
        headers=headers,
        json={
            "client_session_id": "session-1",
            "client_source_id": client_source_id,
            "title": title,
            "body": body,
            "provenance": provenance,
        },
    )
    assert response.status_code == 201, response.text
    return cast(dict[str, object], response.json())


def test_session_accepts_three_sources_and_rejects_a_fourth(tmp_path: Path) -> None:
    client, headers = authenticated_client(tmp_path)
    for index in range(1, 4):
        add_pasted_source(
            client,
            headers,
            client_source_id=f"source-{index}",
            title=f"Source {index}",
            body=f"Distinct source body {index}.",
            provenance=f"Notebook {index}",
        )

    fourth = client.post(
        "/task-creation/pasted-sources",
        headers=headers,
        json={
            "client_session_id": "session-1",
            "client_source_id": "source-4",
            "title": "Source 4",
            "body": "Distinct source body 4.",
            "provenance": "Notebook 4",
        },
    )
    session = client.get("/task-creation/sessions/session-1", headers=headers)

    assert fourth.status_code == 409
    assert fourth.json()["detail"] == "A task creation session can contain at most 3 sources."
    assert session.status_code == 200
    assert session.json()["source_count"] == 3
    assert session.json()["can_add"] is False
    assert [source["kind"] for source in session.json()["sources"]] == [
        "pasted",
        "pasted",
        "pasted",
    ]


def test_normalized_pasted_body_hash_prevents_duplicates_within_session(
    tmp_path: Path,
) -> None:
    client, headers = authenticated_client(tmp_path)
    add_pasted_source(
        client,
        headers,
        client_source_id="source-1",
        title="First title",
        body="Same body.\r\n",
    )

    duplicate = client.post(
        "/task-creation/pasted-sources",
        headers=headers,
        json={
            "client_session_id": "session-1",
            "client_source_id": "source-2",
            "title": "Different title",
            "body": "  Same body.\n",
            "provenance": "Different provenance",
        },
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "This pasted source is already in the session."


def test_sources_can_be_edited_and_deleted_independently(tmp_path: Path) -> None:
    client, headers = authenticated_client(tmp_path)
    first = add_pasted_source(
        client,
        headers,
        client_source_id="source-1",
        title="First",
        body="First body.",
    )
    second = add_pasted_source(
        client,
        headers,
        client_source_id="source-2",
        title="Second",
        body="Second body.",
    )

    edited = client.patch(
        f"/task-creation/pasted-sources/{first['id']}",
        headers=headers,
        json={"title": "Edited first", "body": "Edited body.", "provenance": "Notes"},
    )
    deleted = client.delete(
        f"/task-creation/sources/{second['id']}",
        headers=headers,
    )
    session = client.get("/task-creation/sessions/session-1", headers=headers).json()

    assert edited.status_code == 200
    assert edited.json()["title"] == "Edited first"
    assert deleted.status_code == 204
    assert session["source_count"] == 1
    assert session["sources"][0]["id"] == first["id"]


def test_confirmation_requires_all_sources_ready_and_warning_acceptance(
    tmp_path: Path,
) -> None:
    client, headers = authenticated_client(tmp_path)
    first = add_pasted_source(
        client,
        headers,
        client_source_id="source-1",
        title="First source",
        body="Short first body.",
    )
    second = add_pasted_source(
        client,
        headers,
        client_source_id="source-2",
        title="Second source",
        body="Short second body.",
        provenance="Notebook",
    )
    edited_first = client.patch(
        f"/task-creation/pasted-sources/{first['id']}",
        headers=headers,
        json={
            "title": "First source",
            "body": "Short first body.",
            "provenance": None,
        },
    )
    assert edited_first.json()["input_version"] == 2
    source_ids = [first["id"], second["id"]]
    request = {
        "idempotency_key": "confirm-session-1",
        "client_session_id": "session-1",
        "source_ids": source_ids,
        "accepted_warning_versions": {},
    }

    blocked = client.post("/task-creation/confirm", headers=headers, json=request)
    stale_acceptance = client.post(
        "/task-creation/confirm",
        headers=headers,
        json={
            **request,
            "accepted_warning_versions": {str(first["id"]): 1, str(second["id"]): 1},
        },
    )
    accepted = client.post(
        "/task-creation/confirm",
        headers=headers,
        json={**request, "accepted_warning_versions": {str(first["id"]): 2, str(second["id"]): 1}},
    )
    repeated = client.post(
        "/task-creation/confirm",
        headers=headers,
        json={**request, "accepted_warning_versions": {str(first["id"]): 2, str(second["id"]): 1}},
    )
    consumed_session = client.get(
        "/task-creation/sessions/session-1",
        headers=headers,
    )
    second_confirmation = client.post(
        "/task-creation/confirm",
        headers=headers,
        json={
            **request,
            "idempotency_key": "different-confirmation-key",
            "accepted_warning_versions": {str(first["id"]): 2, str(second["id"]): 1},
        },
    )

    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "Accept every source warning before confirmation."
    assert stale_acceptance.status_code == 409
    assert accepted.status_code == 200
    assert repeated.json() == accepted.json()
    assert consumed_session.json()["source_count"] == 0
    assert second_confirmation.status_code == 409
    assert second_confirmation.json()["detail"] == (
        "Confirmation must include every retained session source exactly once."
    )
    assert accepted.json()["task"]["first_source_title"] == "First source"
    assert accepted.json()["task"]["additional_source_count"] == 1
    assert [revision["title"] for revision in accepted.json()["source_revisions"]] == [
        "First source",
        "Second source",
    ]


def test_mixed_url_file_and_pasted_sources_confirm_in_selected_order(tmp_path: Path) -> None:
    client, headers, dispatcher = mixed_client(tmp_path)
    pasted = add_pasted_source(
        client,
        headers,
        client_source_id="pasted",
        title="Pasted notes",
        body="Pasted body.",
        provenance="Notebook",
    )
    url = client.post(
        "/task-creation/url-sources",
        headers=headers,
        json={
            "client_session_id": "session-1",
            "client_source_id": "url",
            "url": "https://example.com/article",
        },
    ).json()
    dispatcher.run_url()
    file_source = client.post(
        "/task-creation/file-sources",
        headers=headers,
        data={"client_session_id": "session-1", "client_source_id": "file"},
        files={"file": ("brief.md", b"File body.", "text/markdown")},
    ).json()
    dispatcher.run_file()

    session = client.get("/task-creation/sessions/session-1", headers=headers).json()
    assert [source["kind"] for source in session["sources"]] == ["pasted", "url", "file"]
    assert session["can_add"] is False
    assert session["can_confirm"] is True

    selected_order = [file_source["id"], pasted["id"], url["id"]]
    confirmed = client.post(
        "/task-creation/confirm",
        headers=headers,
        json={
            "idempotency_key": "mixed-confirmation",
            "client_session_id": "session-1",
            "source_ids": selected_order,
            "accepted_warning_versions": {
                str(pasted["id"]): 1,
                str(url["id"]): 1,
                str(file_source["id"]): 1,
            },
        },
    )

    assert confirmed.status_code == 200
    assert [revision["title"] for revision in confirmed.json()["source_revisions"]] == [
        "brief",
        "Pasted notes",
        "Fetched article",
    ]
    assert confirmed.json()["task"]["first_source_title"] == "brief"
    assert confirmed.json()["task"]["additional_source_count"] == 2


def test_url_and_file_input_identities_are_deduplicated_within_session(
    tmp_path: Path,
) -> None:
    client, headers, _ = mixed_client(tmp_path)
    first_url = client.post(
        "/task-creation/url-sources",
        headers=headers,
        json={
            "client_session_id": "url-session",
            "client_source_id": "url-1",
            "url": "HTTPS://Example.com:443/article#fragment",
        },
    )
    duplicate_url = client.post(
        "/task-creation/url-sources",
        headers=headers,
        json={
            "client_session_id": "url-session",
            "client_source_id": "url-2",
            "url": "https://example.com/article",
        },
    )
    first_file = client.post(
        "/task-creation/file-sources",
        headers=headers,
        data={"client_session_id": "file-session", "client_source_id": "file-1"},
        files={"file": ("first.txt", b"identical bytes", "text/plain")},
    )
    duplicate_file = client.post(
        "/task-creation/file-sources",
        headers=headers,
        data={"client_session_id": "file-session", "client_source_id": "file-2"},
        files={"file": ("renamed.txt", b"identical bytes", "text/plain")},
    )

    assert first_url.status_code == 201
    assert duplicate_url.status_code == 409
    assert duplicate_url.json()["detail"] == "This URL source is already in the session."
    assert first_file.status_code == 201
    assert duplicate_file.status_code == 409
    assert duplicate_file.json()["detail"] == "This file is already in the session."


def test_deleting_one_prepared_source_preserves_the_other_sources(tmp_path: Path) -> None:
    client, headers, dispatcher = mixed_client(tmp_path)
    pasted = add_pasted_source(
        client,
        headers,
        client_source_id="pasted",
        title="Pasted",
        body="Pasted body.",
    )
    url = client.post(
        "/task-creation/url-sources",
        headers=headers,
        json={
            "client_session_id": "session-1",
            "client_source_id": "url",
            "url": "https://example.com/article",
        },
    ).json()
    dispatcher.run_url()

    deleted = client.delete(f"/task-creation/sources/{url['id']}", headers=headers)
    session = client.get("/task-creation/sessions/session-1", headers=headers).json()

    assert deleted.status_code == 204
    assert session["source_count"] == 1
    assert session["sources"][0]["id"] == pasted["id"]
    replacement = client.post(
        "/task-creation/file-sources",
        headers=headers,
        data={"client_session_id": "session-1", "client_source_id": "file"},
        files={"file": ("replacement.txt", b"Replacement.", "text/plain")},
    )
    assert replacement.status_code == 201


def _entitled(tmp_path: Path) -> str:
    database_url = migrated_database(tmp_path)
    entitle(database_url)
    return database_url
