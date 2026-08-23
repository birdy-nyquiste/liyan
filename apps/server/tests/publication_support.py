"""Helpers for 发布任务 tests: a configured server and a saved article to publish.

No test here reaches LSForum Blog. The submitter double in `blog_support`
records the exact submission it was handed, which is how the request-
construction rules stay observable without a live platform.
"""

import json
from pathlib import Path
from typing import Any

from blog_support import SITE_URL, accepted
from fastapi.testclient import TestClient
from zhiyan_support import (
    DeterministicJwtVerifier,
    RecordingDispatcher,
    confirm_sources,
    migrated_database,
)

from liyan_server.app import create_app
from liyan_server.settings import Settings

__all__ = ["SITE_URL", "accepted", "publication_client", "publish", "saved_article"]

SOURCES = ["四天工作制已经没有争议"]
TITLE = "四天工作制的真问题"
BODY = "工时只是生产方式的一部分。\n\n## 现实条件\n\n改变流程比压缩时间更重要。"

# One shared Blog both writers may reach, and a second site only one may.
# A target says who may publish, never who the article is by.
TARGETS = json.dumps(
    [
        {
            "key": "lsforum",
            "display_name": "LSForum Blog",
            "site_url": SITE_URL,
            "api_base_url": "https://blog.lsforum.org",
            "emails": ["writer@example.com", "second@example.com"],
        },
        {
            "key": "lsforum-cn",
            "display_name": "LSForum 中文站",
            "site_url": "https://cn.blog.lsforum.org",
            "api_base_url": "https://cn.blog.lsforum.org",
            "emails": ["second@example.com"],
        },
    ]
)


def publication_client(
    tmp_path: Path,
) -> tuple[TestClient, dict[str, str], RecordingDispatcher]:
    database_url = migrated_database(tmp_path)
    dispatcher = RecordingDispatcher(database_url)
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
        )
    )
    return client, {"Authorization": "Bearer allowed-token"}, dispatcher


def saved_article(
    client: TestClient,
    headers: dict[str, str],
    dispatcher: RecordingDispatcher,
    *,
    key: str = "save-1",
    title: str = TITLE,
    body: str = BODY,
) -> tuple[str, dict[str, Any]]:
    """Confirm one task, run its 知言, and save one article Revision."""
    task_id, _ = confirm_sources(client, headers, SOURCES)
    dispatcher.run_all()
    saved = client.post(
        f"/tasks/{task_id}/liyan-revisions",
        headers=headers,
        json={
            "idempotency_key": key,
            "base_revision_id": None,
            "title": title,
            "body_markdown": body,
        },
    )
    assert saved.status_code == 201, saved.text
    return task_id, saved.json()["revisions"]["current"]


def publish(
    client: TestClient,
    headers: dict[str, str],
    *,
    task_id: str,
    revision_id: str,
    target_key: str = "lsforum",
    key: str = "publish-1",
    author: str = "Zeng Zong",
    working_copy_hash: str | None = None,
) -> Any:
    return client.post(
        "/publication/publish-tasks",
        headers=headers,
        json={
            "idempotency_key": key,
            "task_id": task_id,
            "revision_id": revision_id,
            "target_key": target_key,
            "author": author,
            "working_copy_hash": working_copy_hash,
        },
    )
