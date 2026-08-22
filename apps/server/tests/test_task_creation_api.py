import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from liyan_server.app import create_app
from liyan_server.auth import InvalidAccessToken, VerifiedIdentity
from liyan_server.settings import Settings


class DeterministicJwtVerifier:
    def __init__(self, identities: dict[str, VerifiedIdentity]) -> None:
        self._identities = identities

    def verify(self, token: str) -> VerifiedIdentity:
        try:
            return self._identities[token]
        except KeyError as error:
            raise InvalidAccessToken from error


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


def authenticated_client(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    identity = VerifiedIdentity(subject="supabase-user-1", email="writer@example.com")
    verifier = DeterministicJwtVerifier({"allowed-token": identity})
    settings = Settings(
        database_url=migrated_database(tmp_path),
        allowed_emails="writer@example.com",
    )
    client = TestClient(create_app(settings, jwt_verifier=verifier))
    return client, {"Authorization": "Bearer allowed-token"}


def test_prepares_a_normalized_source_with_non_blocking_warnings(tmp_path: Path) -> None:
    client, headers = authenticated_client(tmp_path)

    response = client.post(
        "/task-creation/prepare",
        headers=headers,
        json={
            "title": "  A   useful source  ",
            "body": "  First line\r\n\r\nSecond line.  ",
            "provenance": "   ",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "source": {
            "title": "A useful source",
            "body": "First line\n\nSecond line.",
            "provenance": None,
        },
        "warnings": [
            {
                "code": "short_body",
                "message": "The source body is short; confirm that it is complete.",
            },
            {
                "code": "missing_provenance",
                "message": "Provenance is missing; you can still create the task.",
            },
        ],
        "can_confirm": True,
    }


def test_prepare_blocks_blank_required_source_fields(tmp_path: Path) -> None:
    client, headers = authenticated_client(tmp_path)

    response = client.post(
        "/task-creation/prepare",
        headers=headers,
        json={"title": "  ", "body": "\r\n", "provenance": None},
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {"field": "title", "message": "A source title is required."},
            {"field": "body", "message": "A source body is required."},
        ]
    }


def test_confirmation_is_atomic_idempotent_and_allocates_user_scoped_numbers(
    tmp_path: Path,
) -> None:
    client, headers = authenticated_client(tmp_path)
    source = {
        "title": "First source",
        "body": "A complete enough source body.",
        "provenance": "https://example.com/first",
    }

    first = client.post(
        "/task-creation/confirm",
        headers=headers,
        json={"idempotency_key": "create-session-1", "source": source},
    )
    repeated = client.post(
        "/task-creation/confirm",
        headers=headers,
        json={"idempotency_key": "create-session-1", "source": source},
    )
    second = client.post(
        "/task-creation/confirm",
        headers=headers,
        json={
            "idempotency_key": "create-session-2",
            "source": {
                "title": "Second source",
                "body": "Another source body.",
                "provenance": None,
            },
        },
    )

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert repeated.json() == first.json()
    assert first.json()["task"]["number"] == 1
    assert first.json()["task"]["display_name"] == "First source"
    assert first.json()["task"]["first_source_title"] == "First source"
    assert first.json()["task"]["additional_source_count"] == 0
    assert first.json()["task"]["current_version_number"] == 1
    assert first.json()["source_revision"]["title"] == "First source"
    assert second.status_code == 200
    assert second.json()["task"]["number"] == 2

    task_list = client.get("/tasks", headers=headers)
    assert task_list.status_code == 200
    assert [item["number"] for item in task_list.json()["items"]] == [2, 1]
    assert [item["first_source_title"] for item in task_list.json()["items"]] == [
        "Second source",
        "First source",
    ]


def test_reusing_an_idempotency_key_with_different_content_is_rejected(tmp_path: Path) -> None:
    client, headers = authenticated_client(tmp_path)
    request = {
        "idempotency_key": "create-session-1",
        "source": {"title": "Original", "body": "Original body", "provenance": None},
    }
    assert client.post("/task-creation/confirm", headers=headers, json=request).status_code == 200

    changed_request = {
        "idempotency_key": "create-session-1",
        "source": {"title": "Original", "body": "Changed body", "provenance": None},
    }
    response = client.post("/task-creation/confirm", headers=headers, json=changed_request)

    assert response.status_code == 409
    assert response.json() == {
        "detail": "This creation request was already used with different content."
    }


def test_rename_changes_only_the_task_display_name(tmp_path: Path) -> None:
    client, headers = authenticated_client(tmp_path)
    created = client.post(
        "/task-creation/confirm",
        headers=headers,
        json={
            "idempotency_key": "create-session-1",
            "source": {"title": "Source title", "body": "Source body", "provenance": None},
        },
    ).json()
    original_task = created["task"]

    renamed = client.patch(
        f"/tasks/{original_task['id']}",
        headers=headers,
        json={"display_name": "  My research task  "},
    )

    assert renamed.status_code == 200
    assert renamed.json()["display_name"] == "My research task"
    assert renamed.json()["number"] == original_task["number"]
    assert renamed.json()["current_version_id"] == original_task["current_version_id"]
    assert renamed.json()["current_version_number"] == 1
    assert renamed.json()["first_source_title"] == "Source title"
