"""A server whose temporary data a test can age past its TTL.

Cleanup is the one behaviour whose input is elapsed time, so time is passed in
rather than waited for: every test builds real rows through the public API and
then runs the sweep at a chosen moment. No test sleeps, and none reaches R2.
"""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO
from uuid import UUID

from blog_support import DeterministicBlogSubmitter
from fastapi.testclient import TestClient
from publication_support import TARGETS
from sqlalchemy.orm import Session
from zhiyan_support import (
    DeterministicJwtVerifier,
    DeterministicLiyanProvider,
    DeterministicZhiyanProvider,
    migrated_database,
)

from liyan_server.app import create_app
from liyan_server.database import Database, Execution
from liyan_server.file_parse_worker import process_file_parse
from liyan_server.file_parsing import FileParseLimits
from liyan_server.liyan.runs import LIYAN_OPERATION
from liyan_server.liyan.worker import process_liyan_run
from liyan_server.object_storage import ObjectStorage, ObjectStorageState, StoredObject
from liyan_server.publication.runs import PUBLISH_OPERATION
from liyan_server.publication.worker import process_publication_run
from liyan_server.settings import Settings
from liyan_server.zhiyan.worker import process_zhiyan_run


def later(**offset: float) -> datetime:
    """A moment this far after the rows the test just built.

    Anchored to the real clock rather than a fixed date, because the rows are
    stamped by the server as it writes them. Only the offset is the test's
    business, and nothing here waits for it to pass.
    """
    return datetime.now(UTC) + timedelta(**offset)


class MemoryObjectStorage(ObjectStorage):
    """R2 with a dict behind it, including the listing the orphan sweep needs.

    Writes are stamped as they happen, and `place_written_at` puts one down with
    an age of the test's choosing — which is how an orphan can be told apart
    from an upload that is still committing.
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.written_at: dict[str, datetime] = {}
        self.reachable = True

    def put(self, key: str, stream: BinaryIO, *, content_type: str) -> None:
        self.objects[key] = stream.read()
        self.written_at[key] = datetime.now(UTC)

    def place_written_at(self, key: str, body: bytes, written_at: datetime) -> None:
        self.objects[key] = body
        self.written_at[key] = written_at

    def open(self, key: str) -> BinaryIO:
        return BytesIO(self.objects[key])

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)
        self.written_at.pop(key, None)

    def state(self) -> ObjectStorageState:
        return "ready" if self.reachable else "unreachable"

    def list_objects(self, prefix: str = "") -> tuple[StoredObject, ...]:
        return tuple(
            StoredObject(key=key, written_at=self.written_at.get(key, datetime.now(UTC)))
            for key in sorted(self.objects)
            if key.startswith(prefix)
        )


class RecordingExecutionDispatcher:
    """Runs whichever worker each queued Execution belongs to, on demand.

    Confirming a 立言任务 starts 知言 on its own, and a task with runs still in
    flight refuses editing — so a cleanup test that wants a quiet task has to be
    able to finish that work, not just the parse it asked for.
    """

    def __init__(self, database_url: str, storage: ObjectStorage) -> None:
        self.database_url = database_url
        self.storage = storage
        self.execution_ids: list[UUID] = []
        self.provider = DeterministicZhiyanProvider()
        self.liyan_provider = DeterministicLiyanProvider()
        self.blog = DeterministicBlogSubmitter()

    def dispatch(self, execution_id: UUID) -> None:
        self.execution_ids.append(execution_id)

    def run_all(self) -> None:
        while self.execution_ids:
            self.run_next()

    def run_next(self) -> None:
        execution_id = self.execution_ids.pop(0)
        database = Database(self.database_url)
        assert database.engine is not None
        with Session(database.engine) as session:
            execution = session.get(Execution, execution_id)
            operation = execution.operation if execution else None
        database.dispose()
        if operation == "parse_file":
            process_file_parse(
                self.database_url,
                execution_id,
                self.storage,
                limits=FileParseLimits(
                    max_pages=20,
                    max_normalized_characters=10_000,
                    timeout_seconds=10,
                    max_docx_entries=100,
                    max_docx_uncompressed_bytes=1_000_000,
                ),
                short_source_characters=20,
            )
        elif operation == LIYAN_OPERATION:
            process_liyan_run(self.database_url, execution_id, self.liyan_provider, self)
        elif operation == PUBLISH_OPERATION:
            process_publication_run(self.database_url, execution_id, self.blog, "ingest-secret")
        else:
            process_zhiyan_run(self.database_url, execution_id, self.provider, self)


def cleanup_client(
    tmp_path: Path,
) -> tuple[TestClient, dict[str, str], RecordingExecutionDispatcher, MemoryObjectStorage, str]:
    database_url = migrated_database(tmp_path)
    storage = MemoryObjectStorage()
    dispatcher = RecordingExecutionDispatcher(database_url, storage)
    client = TestClient(
        create_app(
            Settings(
                database_url=database_url,
                allowed_emails="writer@example.com,second@example.com",
                publication_targets=TARGETS,
                blog_ingest_token="ingest-secret",
            ),
            jwt_verifier=DeterministicJwtVerifier(),
            execution_dispatcher=dispatcher,
            object_storage=storage,
        )
    )
    return (
        client,
        {"Authorization": "Bearer allowed-token"},
        dispatcher,
        storage,
        database_url,
    )


def confirm_task_creation(
    client: TestClient,
    headers: dict[str, str],
    source_ids: list[str],
    *,
    idempotency_key: str = "key-1",
    session_id: str = "session-1",
) -> str:
    """Turn a 任务创建会话 into a 立言任务; return the task id.

    Named apart from `zhiyan_support.confirm_session`, which takes a different
    argument and answers with a different shape. Two importable helpers sharing
    one name would be a trap in a file that imports from both.
    """
    confirmation = client.post(
        "/task-creation/confirm",
        headers=headers,
        json={
            "idempotency_key": idempotency_key,
            "client_session_id": session_id,
            "source_ids": source_ids,
        },
    )
    assert confirmation.status_code == 200, confirmation.text
    return str(confirmation.json()["task"]["id"])


def upload_file_source(
    client: TestClient,
    headers: dict[str, str],
    *,
    session_id: str = "session-1",
    source_id: str = "source-1",
    filename: str = "notes.md",
    body: bytes = b"# Heading\n\nA body long enough to be a usable source.",
) -> Any:
    return client.post(
        "/task-creation/file-sources",
        headers=headers,
        data={"client_session_id": session_id, "client_source_id": source_id},
        files={"file": (filename, body, "text/markdown")},
    )


def save_article(
    client: TestClient,
    headers: dict[str, str],
    task_id: str,
    *,
    title: str = "四天工作制的真问题",
    body: str = "工时只是生产方式的一部分。",
) -> str:
    """Save one 立言文章 Revision, which is what publishing needs to exist."""
    saved = client.post(
        f"/tasks/{task_id}/liyan-revisions",
        headers=headers,
        json={
            "idempotency_key": "save-1",
            "base_revision_id": None,
            "title": title,
            "body_markdown": body,
        },
    )
    assert saved.status_code == 201, saved.text
    return str(saved.json()["revisions"]["current"]["id"])


def publish_to_blog(
    client: TestClient,
    headers: dict[str, str],
    *,
    task_id: str,
    revision_id: str,
) -> Any:
    return client.post(
        "/publication/publish-tasks",
        headers=headers,
        json={
            "idempotency_key": "publish-1",
            "task_id": task_id,
            "revision_id": revision_id,
            "target_key": "lsforum",
            "author": "Zeng Zong",
            "working_copy_hash": None,
            "acknowledge_existing_preview": False,
        },
    )


def delete_task(client: TestClient, headers: dict[str, str], task_id: str) -> Any:
    return client.request(
        "DELETE", f"/tasks/{task_id}", headers=headers, json={"confirmed": True}
    )
