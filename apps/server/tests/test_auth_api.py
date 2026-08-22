import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from liyan_server.app import create_app
from liyan_server.auth import InvalidAccessToken, VerifiedIdentity
from liyan_server.database import Task
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


def seed_task(database_url: str, owner_id: str) -> str:
    engine = create_engine(database_url)
    with Session(engine) as session:
        task = Task(owner_id=UUID(owner_id))
        session.add(task)
        session.commit()
        task_id = str(task.id)
    engine.dispose()
    return task_id


def test_allowlisted_identity_maps_to_one_local_user_and_its_empty_task_list(
    tmp_path: Path,
) -> None:
    identity = VerifiedIdentity(subject="supabase-user-1", email="writer@example.com")
    verifier = DeterministicJwtVerifier({"allowed-token": identity})
    settings = Settings(
        database_url=migrated_database(tmp_path),
        allowed_emails="writer@example.com",
    )
    client = TestClient(create_app(settings, jwt_verifier=verifier))
    headers = {
        "Authorization": "Bearer allowed-token",
        "X-Owner-Id": "client-supplied-owner",
    }

    first_identity = client.get("/auth/me", headers=headers)
    repeated_identity = client.get("/auth/me", headers=headers)
    task_list = client.get("/tasks", headers=headers)

    assert first_identity.status_code == 200
    assert first_identity.json()["email"] == "writer@example.com"
    assert repeated_identity.json() == first_identity.json()
    assert task_list.status_code == 200
    assert task_list.json() == {"items": []}


def test_non_allowlisted_identity_is_rejected_without_disclosing_configuration(
    tmp_path: Path,
) -> None:
    identity = VerifiedIdentity(subject="supabase-user-2", email="outsider@example.com")
    verifier = DeterministicJwtVerifier({"outsider-token": identity})
    settings = Settings(
        database_url=migrated_database(tmp_path),
        allowed_emails="writer@example.com,editor@example.com",
    )
    client = TestClient(create_app(settings, jwt_verifier=verifier))

    response = client.get(
        "/tasks",
        headers={"Authorization": "Bearer outsider-token"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Access is not available for this account."}
    response_body = response.text.casefold()
    assert "writer@example.com" not in response_body
    assert "editor@example.com" not in response_body


def test_client_supplied_owner_cannot_replace_the_verified_subject(tmp_path: Path) -> None:
    identities = {
        "first-token": VerifiedIdentity("supabase-user-1", "first@example.com"),
        "second-token": VerifiedIdentity("supabase-user-2", "second@example.com"),
    }
    database_url = migrated_database(tmp_path)
    settings = Settings(
        database_url=database_url,
        allowed_emails="first@example.com,second@example.com",
    )
    client = TestClient(
        create_app(settings, jwt_verifier=DeterministicJwtVerifier(identities))
    )

    first = client.get("/auth/me", headers={"Authorization": "Bearer first-token"})
    second = client.get(
        "/auth/me",
        headers={
            "Authorization": "Bearer second-token",
            "X-Owner-Id": first.json()["id"],
        },
    )
    first_task_id = seed_task(database_url, first.json()["id"])
    second_task_id = seed_task(database_url, second.json()["id"])
    second_tasks = client.get(
        "/tasks",
        headers={
            "Authorization": "Bearer second-token",
            "X-Owner-Id": first.json()["id"],
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["email"] == "second@example.com"
    assert second.json()["id"] != first.json()["id"]
    assert second_tasks.json() == {"items": [{"id": second_task_id}]}
    assert first_task_id not in second_tasks.text


def test_task_list_requires_a_verified_bearer_identity(tmp_path: Path) -> None:
    settings = Settings(
        database_url=migrated_database(tmp_path),
        allowed_emails="writer@example.com",
    )
    client = TestClient(
        create_app(settings, jwt_verifier=DeterministicJwtVerifier({}))
    )

    response = client.get("/tasks")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication is required."}
