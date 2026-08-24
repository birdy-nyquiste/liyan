"""Removing what nobody needs, and nothing else.

Cleanup is the only part of 立言阁 that deletes without being asked, so every
test here is as much about what survives as about what goes: a confirmed 来源,
a task inside its retention window, and — always — the publication evidence a
Blog Preview left behind.
"""

from pathlib import Path
from typing import Any

from cleanup_support import (
    MemoryObjectStorage,
    cleanup_client,
    confirm_task_creation,
    delete_task,
    later,
    publish_to_blog,
    save_article,
    upload_file_source,
)
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from liyan_server.cleanup import CleanupPolicy, run_cleanup
from liyan_server.database import (
    Database,
    Execution,
    FileParseResult,
    LiyanArticle,
    LiyanRevision,
    LiyanRunResult,
    PublishTask,
    Source,
    SourceEditSession,
    SourcePreparation,
    SourceRevision,
    Task,
    TaskVersion,
    ZhiyanReport,
)


def test_an_abandoned_upload_and_its_object_expire_together(tmp_path: Path) -> None:
    client, headers, dispatcher, storage, database_url = cleanup_client(tmp_path)
    uploaded = upload_file_source(client, headers)
    assert uploaded.status_code == 201, uploaded.text
    dispatcher.run_all()
    assert len(storage.objects) == 1

    report = run_cleanup(
        database_url, storage, policy=CleanupPolicy(), now=later(hours=25)
    )

    assert report.expired_task_creation_sources == 1
    assert storage.objects == {}
    listed = client.get("/task-creation/sessions/session-1", headers=headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["sources"] == []


def test_an_upload_still_inside_its_window_is_left_where_the_user_left_it(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, storage, database_url = cleanup_client(tmp_path)
    upload_file_source(client, headers)
    dispatcher.run_all()

    report = run_cleanup(
        database_url, storage, policy=CleanupPolicy(), now=later(hours=23)
    )

    assert report.expired_task_creation_sources == 0
    assert len(storage.objects) == 1
    listed = client.get("/task-creation/sessions/session-1", headers=headers)
    assert len(listed.json()["sources"]) == 1


def _task_with_an_edit_session(
    tmp_path: Path,
) -> tuple[TestClient, dict[str, str], MemoryObjectStorage, str, dict[str, Any]]:
    client, headers, dispatcher, storage, database_url = cleanup_client(tmp_path)
    uploaded = upload_file_source(client, headers)
    dispatcher.run_all()
    task_id = confirm_task_creation(client, headers, [uploaded.json()["id"]])
    # Confirmation starts 知言 on its own, and a task with runs in flight
    # refuses editing. Let them finish so the state under test is the quiet one.
    dispatcher.run_all()
    started = client.post(f"/tasks/{task_id}/source-edit-sessions", headers=headers)
    assert started.status_code == 201, started.text
    return client, headers, storage, database_url, started.json()


def test_a_discarded_editing_checkpoint_stops_taking_up_room(tmp_path: Path) -> None:
    client, headers, storage, database_url, edit = _task_with_an_edit_session(tmp_path)
    discarded = client.post(f"/source-edit-sessions/{edit['id']}/discard", headers=headers)
    assert discarded.status_code == 204, discarded.text

    report = run_cleanup(database_url, storage, policy=CleanupPolicy(), now=later(hours=25))

    assert report.expired_source_edit_sessions == 1


def test_an_editing_checkpoint_left_open_and_forgotten_expires_too(tmp_path: Path) -> None:
    """Abandoned is the common case: a tab closed without discarding or saving.

    Nothing marks it, so only elapsed time can tell it from an edit in progress —
    and the checkpoint was never recoverable in the first place.
    """
    client, headers, storage, database_url, _ = _task_with_an_edit_session(tmp_path)

    report = run_cleanup(database_url, storage, policy=CleanupPolicy(), now=later(hours=25))

    assert report.expired_source_edit_sessions == 1


def test_an_editing_checkpoint_someone_is_still_using_is_left_alone(tmp_path: Path) -> None:
    client, headers, storage, database_url, _ = _task_with_an_edit_session(tmp_path)

    report = run_cleanup(database_url, storage, policy=CleanupPolicy(), now=later(hours=23))

    assert report.expired_source_edit_sessions == 0


def test_a_confirmed_source_is_business_data_and_never_expires(tmp_path: Path) -> None:
    """Once a 来源 belongs to a 立言任务 it ages with the task, not the browser.

    The TTL here is a browser session's, and a confirmed 来源 has outlived that
    session by definition — expiring it would delete part of a live task.
    """
    client, headers, dispatcher, storage, database_url = cleanup_client(tmp_path)
    uploaded = upload_file_source(client, headers)
    dispatcher.run_all()
    confirm_task_creation(client, headers, [uploaded.json()["id"]])

    report = run_cleanup(
        database_url, storage, policy=CleanupPolicy(), now=later(days=365)
    )

    assert report.expired_task_creation_sources == 0
    assert len(storage.objects) == 1


def _published_then_deleted(
    tmp_path: Path,
) -> tuple[TestClient, dict[str, str], MemoryObjectStorage, str, str]:
    """A 立言任务 that reached Blog and was then deleted by its owner."""
    client, headers, dispatcher, storage, database_url = cleanup_client(tmp_path)
    uploaded = upload_file_source(client, headers)
    dispatcher.run_all()
    task_id = confirm_task_creation(client, headers, [uploaded.json()["id"]])
    dispatcher.run_all()
    revision_id = save_article(client, headers, task_id)
    published = publish_to_blog(client, headers, task_id=task_id, revision_id=revision_id)
    assert published.status_code == 202, published.text
    dispatcher.run_all()
    removed = delete_task(client, headers, task_id)
    assert removed.status_code == 204, removed.text
    return client, headers, storage, database_url, task_id


def test_a_deleted_task_keeps_its_data_for_thirty_days(tmp_path: Path) -> None:
    """Deletion hides the task immediately; removal is a separate, later act.

    The window is not a recovery path — nothing exposes the rows in it. It is
    the room the product keeps to answer questions about what was submitted.
    """
    client, headers, storage, database_url, _ = _published_then_deleted(tmp_path)

    report = run_cleanup(database_url, storage, policy=CleanupPolicy(), now=later(days=29))

    assert report.purged_tasks == 0
    assert len(storage.objects) == 1


def test_a_deleted_task_is_physically_gone_after_thirty_days(tmp_path: Path) -> None:
    client, headers, storage, database_url, task_id = _published_then_deleted(tmp_path)

    report = run_cleanup(database_url, storage, policy=CleanupPolicy(), now=later(days=31))

    assert report.purged_tasks == 1
    assert storage.objects == {}
    assert client.get("/tasks", headers=headers).json()["items"] == []
    # Still gone, not merely hidden: nothing brings it back into view.
    assert client.get(f"/tasks/{task_id}/versions", headers=headers).status_code == 404


def test_publication_evidence_outlives_the_task_it_came_from(tmp_path: Path) -> None:
    """The point of the whole retention rule: a Preview URL survives everything.

    The 立言任务, its 来源, its article, and its uploaded file are all gone. What
    was submitted to Blog, and the Preview it produced, are still answerable.
    """
    client, headers, storage, database_url, _ = _published_then_deleted(tmp_path)

    run_cleanup(database_url, storage, policy=CleanupPolicy(), now=later(days=31))

    records = client.get("/publication/publish-tasks", headers=headers)
    assert records.status_code == 200, records.text
    kept = records.json()["items"]
    assert len(kept) == 1
    assert kept[0]["status"] == "succeeded"
    assert kept[0]["preview_url"] is not None
    assert kept[0]["title"] == "四天工作制的真问题"
    assert kept[0]["attempts"] != []


def test_running_cleanup_twice_removes_nothing_the_second_time(tmp_path: Path) -> None:
    client, headers, storage, database_url, _ = _published_then_deleted(tmp_path)

    first = run_cleanup(database_url, storage, policy=CleanupPolicy(), now=later(days=31))
    again = run_cleanup(database_url, storage, policy=CleanupPolicy(), now=later(days=31))

    assert first.purged_tasks == 1
    assert again.purged_tasks == 0
    assert again.removed_objects == 0
    assert client.get("/publication/publish-tasks", headers=headers).json()["items"] != []


def test_an_object_no_row_remembers_is_collected(tmp_path: Path) -> None:
    """The leak an ordered delete cannot prevent: a crash before the row exists.

    An upload writes to R2 and only then commits its 来源. Interrupted in that
    gap, the object is invisible to every query in the server, so the only way
    to find it is to ask storage what it is holding.
    """
    client, headers, dispatcher, storage, database_url = cleanup_client(tmp_path)
    storage.place_written_at(
        "users/someone/source-preparations/lost/v1/orphan.md",
        b"nobody's",
        written_at=later(hours=-48),
    )

    report = run_cleanup(database_url, storage, policy=CleanupPolicy(), now=later(hours=25))

    assert report.removed_objects == 1
    assert storage.objects == {}


def test_an_object_a_live_source_still_needs_is_never_collected(tmp_path: Path) -> None:
    client, headers, dispatcher, storage, database_url = cleanup_client(tmp_path)
    uploaded = upload_file_source(client, headers)
    dispatcher.run_all()
    confirm_task_creation(client, headers, [uploaded.json()["id"]])

    report = run_cleanup(database_url, storage, policy=CleanupPolicy(), now=later(days=365))

    assert report.removed_objects == 0
    assert len(storage.objects) == 1


def test_an_object_written_moments_ago_survives_a_sweep_mid_upload(tmp_path: Path) -> None:
    """A sweep must not race an upload that has written but not yet committed.

    Between `put` and the row's commit the object looks exactly like an orphan.
    Only its age separates the two, so the sweep collects nothing recent.
    """
    client, headers, dispatcher, storage, database_url = cleanup_client(tmp_path)
    storage.place_written_at(
        "users/someone/source-preparations/in-flight/v1/now.md",
        b"committing",
        written_at=later(),
    )

    report = run_cleanup(database_url, storage, policy=CleanupPolicy(), now=later(hours=1))

    assert report.removed_objects == 0
    assert len(storage.objects) == 1


def test_one_writers_purge_never_reaches_another_writers_task(tmp_path: Path) -> None:
    """Cleanup decides per row, so two owners in the same sweep stay separate.

    Both tasks are the same age and both are swept in the same run; only the
    one whose owner deleted it goes.
    """
    client, headers, dispatcher, storage, database_url = cleanup_client(tmp_path)
    theirs = {"Authorization": "Bearer second-token"}
    mine = upload_file_source(client, headers)
    dispatcher.run_all()
    my_task = confirm_task_creation(client, headers, [mine.json()["id"]])
    dispatcher.run_all()
    yours = upload_file_source(
        client, theirs, session_id="session-2", source_id="source-2", filename="theirs.md"
    )
    dispatcher.run_all()
    their_task = confirm_task_creation(
        client, theirs, [yours.json()["id"]], idempotency_key="key-2", session_id="session-2"
    )
    dispatcher.run_all()
    assert delete_task(client, headers, my_task).status_code == 204

    report = run_cleanup(database_url, storage, policy=CleanupPolicy(), now=later(days=31))

    assert report.purged_tasks == 1
    assert [item["id"] for item in client.get("/tasks", headers=theirs).json()["items"]] == [
        their_task
    ]
    assert client.get("/tasks", headers=headers).json()["items"] == []
    assert len(storage.objects) == 1


def _rows(database_url: str, statement: Any) -> list[Any]:
    """Read rows directly, for leaks no endpoint would ever show."""
    database = Database(database_url)
    assert database.engine is not None
    with Session(database.engine) as session:
        found = list(session.scalars(statement))
    database.dispose()
    return found


def test_an_expired_upload_leaves_no_execution_or_parse_result_behind(
    tmp_path: Path,
) -> None:
    """The rows nothing would ever show again if they were left.

    An Execution's target is a plain identifier with no foreign key, so nothing
    cascades on any backend — an abandoned upload would leak one Execution and
    one parse result forever, invisibly.
    """
    client, headers, dispatcher, storage, database_url = cleanup_client(tmp_path)
    upload_file_source(client, headers)
    dispatcher.run_all()
    assert _rows(database_url, select(Execution)) != []
    assert _rows(database_url, select(FileParseResult)) != []

    run_cleanup(database_url, storage, policy=CleanupPolicy(), now=later(hours=25))

    assert _rows(database_url, select(Execution)) == []
    assert _rows(database_url, select(FileParseResult)) == []
    assert _rows(database_url, select(SourcePreparation)) == []


def test_a_purged_task_leaves_no_row_of_its_own_behind(tmp_path: Path) -> None:
    """Everything belonging to the task, named explicitly.

    SQLite does not enforce foreign keys here, so a purge that leaned on
    ON DELETE CASCADE would leave every one of these rows and still pass. They
    are asserted by table for that reason.
    """
    client, headers, storage, database_url, _ = _published_then_deleted(tmp_path)

    run_cleanup(database_url, storage, policy=CleanupPolicy(), now=later(days=31))

    for table in (
        Task,
        TaskVersion,
        Source,
        SourceRevision,
        SourcePreparation,
        SourceEditSession,
        ZhiyanReport,
        LiyanArticle,
        LiyanRevision,
        LiyanRunResult,
        FileParseResult,
    ):
        assert _rows(database_url, select(table)) == [], table.__name__
    # The 发布任务 and the Execution that attempted it are the exception.
    assert len(_rows(database_url, select(PublishTask))) == 1
    attempts = _rows(database_url, select(Execution))
    assert [execution.target_type for execution in attempts] == ["publish_task"]


def test_a_source_whose_parse_is_still_running_is_not_swept_out_from_under_it(
    tmp_path: Path,
) -> None:
    """Queued work outlives the TTL: the worker is about to write to this row.

    Age alone would call an upload abandoned while its parse sits in the queue
    behind a backlog, and deleting it would fail the run for no reason.
    """
    client, headers, dispatcher, storage, database_url = cleanup_client(tmp_path)
    upload_file_source(client, headers)
    # Deliberately not run: the parse Execution stays queued.

    report = run_cleanup(database_url, storage, policy=CleanupPolicy(), now=later(hours=25))

    assert report.expired_task_creation_sources == 0
    assert len(storage.objects) == 1


def test_a_saved_editing_checkpoint_is_history_and_is_kept(tmp_path: Path) -> None:
    """A saved checkpoint says which edit produced a 任务版本, so it is not litter.

    Age cannot be the rule here: this row stays useful for exactly as long as
    the 任务版本 it explains, which outlives any session TTL.
    """
    client, headers, storage, database_url, edit = _task_with_an_edit_session(tmp_path)
    source = edit["base_version"]["sources"][0]
    saved = client.post(
        f"/source-edit-sessions/{edit['id']}/save",
        headers=headers,
        json={
            "idempotency_key": "save-edit-1",
            "sources": [
                {
                    "source_id": source["source_id"],
                    "base_revision_id": source["id"],
                    "content": {
                        "title": "改过的标题",
                        "body": source["body"] + "\n又改了一句。",
                        "provenance": source["provenance"],
                    },
                }
            ],
        },
    )
    assert saved.status_code == 200, saved.text

    report = run_cleanup(database_url, storage, policy=CleanupPolicy(), now=later(days=365))

    assert report.expired_source_edit_sessions == 0
    assert _rows(database_url, select(SourceEditSession)) != []


def test_an_unreachable_bucket_never_costs_the_only_pointer_to_an_object(
    tmp_path: Path,
) -> None:
    """If R2 cannot answer, the row that names the key has to stay.

    Deleting it would leave the object with nothing pointing at it, findable
    only by a later listing — which the same outage also prevents.
    """
    client, headers, dispatcher, storage, database_url = cleanup_client(tmp_path)
    upload_file_source(client, headers)
    dispatcher.run_all()
    storage.reachable = False

    report = run_cleanup(database_url, storage, policy=CleanupPolicy(), now=later(hours=25))

    assert report.storage_ready is False
    assert report.expired_task_creation_sources == 0
    assert report.removed_objects == 0
    assert len(storage.objects) == 1
    # And the next healthy run finishes the job.
    storage.reachable = True
    recovered = run_cleanup(database_url, storage, policy=CleanupPolicy(), now=later(hours=25))
    assert recovered.expired_task_creation_sources == 1
    assert storage.objects == {}
