"""发布任务 safety when Blog fails, answers ambiguously, or is asked twice.

Every rule here exists to keep one Revision from becoming two Blog items. The
Blog v0.11 API offers neither an idempotency key nor a Preview lookup, so 立言阁
cannot discover a duplicate after the fact — it can only refuse to create one.
"""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from publication_support import publish, ready_to_publish, submitter_of
from zhiyan_support import RecordingDispatcher

from liyan_server.publication.blog import (
    UNKNOWN_OUTCOME_MESSAGE,
    BlogOutcomeUnknown,
    BlogSubmissionFailure,
)


def test_one_revision_and_target_pair_can_never_create_a_second_preview(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, revision = ready_to_publish(tmp_path)
    first = publish(client, headers, task_id=task_id, revision_id=revision["id"], key="publish-1")
    assert first.status_code == 202, first.text
    dispatcher.run_all()

    again = publish(client, headers, task_id=task_id, revision_id=revision["id"], key="publish-2")

    assert again.status_code == 409, again.text
    assert len(submitter_of(dispatcher).submissions) == 1


def _retry(client: TestClient, headers: dict[str, str], publish_task_id: str, key: str) -> Any:
    return client.post(
        f"/publication/publish-tasks/{publish_task_id}/retry",
        headers=headers,
        json={"idempotency_key": key},
    )


def _failed_publication(
    tmp_path: Path,
) -> tuple[TestClient, dict[str, str], RecordingDispatcher, dict[str, Any]]:
    """One 发布任务 Blog definitively refused, so nothing was created."""
    client, headers, dispatcher, task_id, revision = ready_to_publish(tmp_path)
    submitter_of(dispatcher).outcomes.append(
        BlogSubmissionFailure("provider_unreachable", "Blog 暂时无法提交，请稍后重试。")
    )
    confirmed = publish(client, headers, task_id=task_id, revision_id=revision["id"])
    assert confirmed.status_code == 202, confirmed.text
    dispatcher.run_all()
    return client, headers, dispatcher, confirmed.json()


def test_a_definitive_failure_is_retried_against_the_original_snapshot(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, confirmed = _failed_publication(tmp_path)

    retried = _retry(client, headers, confirmed["id"], "retry-1")
    dispatcher.run_all()

    assert retried.status_code == 202, retried.text
    resulting = client.get(
        f"/publication/publish-tasks/{confirmed['id']}", headers=headers
    ).json()
    assert resulting["status"] == "succeeded"
    assert resulting["preview_url"] is not None
    submissions = submitter_of(dispatcher).submissions
    assert len(submissions) == 2
    # Byte for byte the first attempt: a retry may not carry a newer article,
    # a different author, or anything else the user has changed since.
    assert submissions[1] == submissions[0]
    assert [attempt["attempt"] for attempt in resulting["attempts"]] == [1, 2]


def test_a_publication_that_never_reached_the_queue_is_retried_the_same_way(
    tmp_path: Path,
) -> None:
    """The pre-send arm: the attempt failed before a request was ever built.

    Nothing left the process, so this is as definitive as a refusal from Blog —
    and it must not need a different route back, or "can this be retried" would
    depend on how early it broke.
    """
    client, headers, dispatcher, task_id, revision = ready_to_publish(tmp_path)
    queued: list[object] = []

    def refuse(execution_id: object, operation: str) -> None:
        raise RuntimeError("The broker is unreachable.")

    dispatcher.dispatch = refuse  # type: ignore[method-assign]
    started = publish(client, headers, task_id=task_id, revision_id=revision["id"])
    assert started.json()["status"] == "failed"
    dispatcher.dispatch = (  # type: ignore[method-assign]
        lambda execution_id, operation: queued.append(execution_id)
    )

    retried = _retry(client, headers, started.json()["id"], "retry-1")

    assert retried.status_code == 202, retried.text
    assert len(queued) == 1
    assert submitter_of(dispatcher).submissions == []


def test_an_unknown_outcome_can_never_be_retried(tmp_path: Path) -> None:
    client, headers, dispatcher, task_id, revision = ready_to_publish(tmp_path)
    # A 201 Blog would not confirm as a Preview: it created something nobody
    # here can see, so a resend is exactly the duplicate ADR-0001 refuses.
    submitter_of(dispatcher).outcomes.append(BlogOutcomeUnknown("Blog responded 500."))
    confirmed = publish(client, headers, task_id=task_id, revision_id=revision["id"]).json()
    dispatcher.run_all()

    refused = _retry(client, headers, confirmed["id"], "retry-1")

    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == UNKNOWN_OUTCOME_MESSAGE
    assert len(submitter_of(dispatcher).submissions) == 1


def test_a_created_preview_can_never_be_retried(tmp_path: Path) -> None:
    client, headers, dispatcher, task_id, revision = ready_to_publish(tmp_path)
    confirmed = publish(client, headers, task_id=task_id, revision_id=revision["id"]).json()
    dispatcher.run_all()

    refused = _retry(client, headers, confirmed["id"], "retry-1")

    assert refused.status_code == 409, refused.text
    assert len(submitter_of(dispatcher).submissions) == 1


def test_a_submission_still_in_flight_cannot_be_retried_alongside_itself(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, revision = ready_to_publish(tmp_path)
    confirmed = publish(client, headers, task_id=task_id, revision_id=revision["id"]).json()

    refused = _retry(client, headers, confirmed["id"], "retry-1")
    dispatcher.run_all()

    assert refused.status_code == 409, refused.text
    assert len(submitter_of(dispatcher).submissions) == 1


def test_one_user_cannot_retry_another_users_publication(tmp_path: Path) -> None:
    client, headers, dispatcher, confirmed = _failed_publication(tmp_path)

    refused = _retry(
        client, {"Authorization": "Bearer second-token"}, confirmed["id"], "retry-1"
    )
    dispatcher.run_all()

    assert refused.status_code == 404, refused.text
    assert len(submitter_of(dispatcher).submissions) == 1


def test_a_repeated_retry_never_starts_a_second_attempt(tmp_path: Path) -> None:
    client, headers, dispatcher, confirmed = _failed_publication(tmp_path)

    first = _retry(client, headers, confirmed["id"], "retry-1")
    again = _retry(client, headers, confirmed["id"], "retry-1")
    dispatcher.run_all()

    assert first.status_code == 202, first.text
    assert again.status_code == 409, again.text
    assert len(submitter_of(dispatcher).submissions) == 2


def _save_again(
    client: TestClient, headers: dict[str, str], task_id: str, base_revision_id: str
) -> dict[str, Any]:
    saved = client.post(
        f"/tasks/{task_id}/liyan-revisions",
        headers=headers,
        json={
            "idempotency_key": "save-2",
            "base_revision_id": base_revision_id,
            "title": "四天工作制的真问题（修订）",
            "body_markdown": "工时只是生产方式的一部分。\n\n## 现实条件\n\n先改流程。",
        },
    )
    assert saved.status_code == 201, saved.text
    current: dict[str, Any] = saved.json()["revisions"]["current"]
    return current


def test_a_newer_revision_reaches_the_same_target_only_after_an_explicit_warning(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, first = ready_to_publish(tmp_path)
    published = publish(client, headers, task_id=task_id, revision_id=first["id"], key="publish-1")
    assert published.status_code == 202, published.text
    dispatcher.run_all()
    newer = _save_again(client, headers, task_id, first["id"])

    unwarned = publish(client, headers, task_id=task_id, revision_id=newer["id"], key="publish-2")

    assert unwarned.status_code == 412, unwarned.text
    assert len(submitter_of(dispatcher).submissions) == 1


def test_a_retry_cannot_slip_past_the_warning_a_newer_revision_already_cleared(
    tmp_path: Path,
) -> None:
    """The oldest way to two Blog items: publish B, then retry A behind it.

    Retrying A is not a repeat of A — by the time it runs, the target may hold
    B. Nothing about A's own failure says so, which is why the check is on the
    task and target rather than on this 发布任务's history.
    """
    client, headers, dispatcher, task_id, first = ready_to_publish(tmp_path)
    submitter_of(dispatcher).outcomes.append(
        BlogSubmissionFailure("provider_unreachable", "Blog 暂时无法提交，请稍后重试。")
    )
    failed = publish(client, headers, task_id=task_id, revision_id=first["id"], key="publish-1")
    dispatcher.run_all()
    newer = _save_again(client, headers, task_id, first["id"])
    published = publish(
        client,
        headers,
        task_id=task_id,
        revision_id=newer["id"],
        key="publish-2",
        acknowledge_existing_preview=True,
    )
    assert published.status_code == 202, published.text
    dispatcher.run_all()

    unwarned = _retry(client, headers, failed.json()["id"], "retry-1")
    dispatcher.run_all()

    assert unwarned.status_code == 412, unwarned.text
    assert len(submitter_of(dispatcher).submissions) == 2


def test_an_acknowledged_retry_may_still_resend_behind_a_newer_revision(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, first = ready_to_publish(tmp_path)
    submitter_of(dispatcher).outcomes.append(
        BlogSubmissionFailure("provider_unreachable", "Blog 暂时无法提交，请稍后重试。")
    )
    failed = publish(client, headers, task_id=task_id, revision_id=first["id"], key="publish-1")
    dispatcher.run_all()
    newer = _save_again(client, headers, task_id, first["id"])
    publish(
        client,
        headers,
        task_id=task_id,
        revision_id=newer["id"],
        key="publish-2",
        acknowledge_existing_preview=True,
    )
    dispatcher.run_all()

    acknowledged = client.post(
        f"/publication/publish-tasks/{failed.json()['id']}/retry",
        headers=headers,
        json={"idempotency_key": "retry-1", "acknowledge_existing_preview": True},
    )
    dispatcher.run_all()

    assert acknowledged.status_code == 202, acknowledged.text
    submissions = submitter_of(dispatcher).submissions
    assert len(submissions) == 3
    # Still the original snapshot, warning or no warning.
    assert submissions[2] == submissions[0]


def test_an_acknowledged_warning_lets_a_newer_revision_create_its_own_preview(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, first = ready_to_publish(tmp_path)
    publish(client, headers, task_id=task_id, revision_id=first["id"], key="publish-1")
    dispatcher.run_all()
    newer = _save_again(client, headers, task_id, first["id"])

    acknowledged = publish(
        client,
        headers,
        task_id=task_id,
        revision_id=newer["id"],
        key="publish-2",
        acknowledge_existing_preview=True,
    )
    dispatcher.run_all()

    assert acknowledged.status_code == 202, acknowledged.text
    submissions = submitter_of(dispatcher).submissions
    assert len(submissions) == 2
    # A distinct Blog item, which is the whole point of the warning.
    assert submissions[1].title == newer["title"]


def test_the_warning_also_guards_a_target_whose_outcome_was_never_confirmed(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, first = ready_to_publish(tmp_path)
    # Blog may be holding an item from this attempt, so a newer Revision risks a
    # second one exactly as much as a confirmed Preview does.
    submitter_of(dispatcher).outcomes.append(BlogOutcomeUnknown("Blog responded 500."))
    publish(client, headers, task_id=task_id, revision_id=first["id"], key="publish-1")
    dispatcher.run_all()
    newer = _save_again(client, headers, task_id, first["id"])

    unwarned = publish(client, headers, task_id=task_id, revision_id=newer["id"], key="publish-2")

    assert unwarned.status_code == 412, unwarned.text
    assert len(submitter_of(dispatcher).submissions) == 1


def test_a_definitive_failure_leaves_no_warning_for_a_newer_revision_to_clear(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, first = ready_to_publish(tmp_path)
    submitter_of(dispatcher).outcomes.append(
        BlogSubmissionFailure("provider_unreachable", "Blog 暂时无法提交，请稍后重试。")
    )
    publish(client, headers, task_id=task_id, revision_id=first["id"], key="publish-1")
    dispatcher.run_all()
    newer = _save_again(client, headers, task_id, first["id"])

    # Nothing was created, so there is no second Blog item to warn about.
    published = publish(client, headers, task_id=task_id, revision_id=newer["id"], key="publish-2")
    dispatcher.run_all()

    assert published.status_code == 202, published.text
    assert len(submitter_of(dispatcher).submissions) == 2
