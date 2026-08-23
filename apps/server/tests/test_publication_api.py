"""Submitting an eligible Revision to an authorized Blog target as a Preview."""

from pathlib import Path

from blog_support import SITE_URL, accepted
from publication_support import (
    publication_client,
    publish,
    ready_to_publish,
    submitter_of,
)

from liyan_server.publication.blog import (
    BlogOutcomeUnknown,
    BlogPreviewAccepted,
    BlogSubmissionFailure,
)


def test_only_targets_the_server_authorized_for_this_user_are_selectable(
    tmp_path: Path,
) -> None:
    client, headers, _ = publication_client(tmp_path)

    mine = client.get("/publication/targets", headers=headers)
    theirs = client.get(
        "/publication/targets", headers={"Authorization": "Bearer second-token"}
    )

    assert mine.status_code == 200, mine.text
    assert [item["key"] for item in mine.json()["items"]] == ["lsforum"]
    assert [item["key"] for item in theirs.json()["items"]] == ["lsforum", "lsforum-cn"]


def test_a_target_never_exposes_the_credential_the_server_publishes_with(
    tmp_path: Path,
) -> None:
    client, headers, _ = publication_client(tmp_path)

    listed = client.get("/publication/targets", headers=headers)

    assert "ingest-secret" not in listed.text
    assert listed.json()["items"][0] == {
        "key": "lsforum",
        "platform": "lsforum_blog",
        "display_name": "LSForum Blog",
        "site_url": SITE_URL,
    }


def test_blog_receives_the_author_the_user_typed_at_confirmation(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, revision = ready_to_publish(tmp_path)
    publish(
        client, headers, task_id=task_id, revision_id=revision["id"], author="  曾总  "
    )

    dispatcher.run_all()

    from liyan_server.publication.blog import submission_body

    # Blog treats one name as one author across submissions, so the stray
    # spacing must not create a second one.
    assert submission_body(submitter_of(dispatcher).submissions[0])["author"] == {
        "name": "曾总"
    }


def test_an_author_nobody_typed_is_refused_before_anything_is_locked(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, revision = ready_to_publish(tmp_path)

    rejected = publish(
        client, headers, task_id=task_id, revision_id=revision["id"], author="   "
    )

    assert rejected.status_code == 422, rejected.text
    assert not dispatcher.execution_ids


def test_the_publication_center_offers_the_newest_saved_revision_of_each_task(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, first = ready_to_publish(tmp_path)
    second = client.post(
        f"/tasks/{task_id}/liyan-revisions",
        headers=headers,
        json={
            "idempotency_key": "save-2",
            "base_revision_id": first["id"],
            "title": "四天工作制的真问题（修订）",
            "body_markdown": first["body_markdown"],
        },
    )
    assert second.status_code == 201, second.text

    eligible = client.get("/publication/eligible-articles", headers=headers)

    assert eligible.status_code == 200, eligible.text
    items = eligible.json()["items"]
    assert [item["revision_id"] for item in items] == [
        second.json()["revisions"]["current"]["id"]
    ]
    assert items[0]["task_id"] == task_id
    assert items[0]["revision_number"] == 2
    assert items[0]["body_markdown"] == first["body_markdown"]


def test_a_task_without_a_saved_revision_offers_nothing_to_publish(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher = publication_client(tmp_path)
    from zhiyan_support import confirm_sources

    confirm_sources(client, headers, ["四天工作制已经没有争议"])
    dispatcher.run_all()

    eligible = client.get("/publication/eligible-articles", headers=headers)

    assert eligible.json()["items"] == []


def test_confirmation_rejects_a_revision_that_is_no_longer_the_newest_saved_one(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, first = ready_to_publish(tmp_path)
    superseded = client.post(
        f"/tasks/{task_id}/liyan-revisions",
        headers=headers,
        json={
            "idempotency_key": "save-2",
            "base_revision_id": first["id"],
            "title": "四天工作制的真问题（修订）",
            "body_markdown": first["body_markdown"],
        },
    )
    assert superseded.status_code == 201, superseded.text

    rejected = publish(client, headers, task_id=task_id, revision_id=first["id"])

    assert rejected.status_code == 409, rejected.text
    assert not dispatcher.execution_ids


def test_confirmation_rejects_a_draft_that_still_holds_unsaved_edits(
    tmp_path: Path,
) -> None:
    client, headers, _, task_id, revision = ready_to_publish(tmp_path)

    rejected = publish(
        client,
        headers,
        task_id=task_id,
        revision_id=revision["id"],
        working_copy_hash="0" * 64,
    )

    assert rejected.status_code == 409, rejected.text
    assert "未保存" in rejected.json()["detail"]


def test_confirmation_rejects_a_target_this_user_is_not_authorized_for(
    tmp_path: Path,
) -> None:
    client, headers, _, task_id, revision = ready_to_publish(tmp_path)

    rejected = publish(
        client, headers, task_id=task_id, revision_id=revision["id"], target_key="lsforum-cn"
    )

    assert rejected.status_code == 404, rejected.text


def test_confirmation_locks_the_snapshot_before_anything_is_dispatched(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, revision = ready_to_publish(tmp_path)

    started = publish(client, headers, task_id=task_id, revision_id=revision["id"])

    assert started.status_code == 202, started.text
    payload = started.json()
    assert payload["status"] == "pending"
    assert payload["title"] == revision["title"]
    assert payload["body_markdown"] == revision["body_markdown"]
    assert payload["revision_id"] == revision["id"]
    assert payload["revision_number"] == revision["number"]
    assert payload["author"] == "Zeng Zong"
    assert payload["target"]["display_name"] == "LSForum Blog"
    assert payload["post_type"] == "opinion"
    assert payload["requested_status"] == "preview"
    assert payload["preview_url"] is None
    assert len(dispatcher.execution_ids) == 1


def test_a_later_revision_cannot_change_what_a_confirmed_publication_sends(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, revision = ready_to_publish(tmp_path)
    started = publish(client, headers, task_id=task_id, revision_id=revision["id"])
    assert started.status_code == 202, started.text
    replaced = client.post(
        f"/tasks/{task_id}/liyan-revisions",
        headers=headers,
        json={
            "idempotency_key": "save-2",
            "base_revision_id": revision["id"],
            "title": "完全不同的标题",
            "body_markdown": "完全不同的正文。",
        },
    )
    assert replaced.status_code == 201, replaced.text

    dispatcher.run_all()

    submission = submitter_of(dispatcher).submissions[0]
    assert submission.title == revision["title"]
    assert submission.body_markdown == revision["body_markdown"]


def test_the_blog_request_carries_only_the_fields_the_mvp_contract_requires(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, revision = ready_to_publish(tmp_path)
    publish(client, headers, task_id=task_id, revision_id=revision["id"])

    dispatcher.run_all()

    from liyan_server.publication.blog import submission_body, submission_url

    submission = submitter_of(dispatcher).submissions[0]
    assert submission_url(submission) == "https://blog.lsforum.org/api/v1/posts"
    assert submission_body(submission) == {
        "title": revision["title"],
        "content": revision["body_markdown"],
        "author": {"name": "Zeng Zong"},
        "postType": "opinion",
        "status": "preview",
    }


def test_a_confirmed_preview_becomes_the_terminal_successful_outcome(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, revision = ready_to_publish(tmp_path)
    started = publish(client, headers, task_id=task_id, revision_id=revision["id"])

    dispatcher.run_all()

    finished = client.get(
        f"/publication/publish-tasks/{started.json()['id']}", headers=headers
    )
    assert finished.status_code == 200, finished.text
    payload = finished.json()
    assert payload["status"] == "succeeded"
    assert payload["preview_url"] == f"{SITE_URL}/preview/four-day-week-abc123"
    assert payload["external_slug"] == "four-day-week"
    assert payload["external_version"] == "1"
    assert payload["failure_message"] is None


def test_a_created_preview_is_evidence_the_server_can_show_again_later(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, revision = ready_to_publish(tmp_path)
    started = publish(client, headers, task_id=task_id, revision_id=revision["id"])
    dispatcher.run_all()

    stored = client.get(
        f"/publication/publish-tasks/{started.json()['id']}", headers=headers
    )

    assert stored.json()["response_evidence"]["previewPath"] == (
        "/preview/four-day-week-abc123"
    )
    assert stored.json()["response_evidence"]["status"] == "preview"


def test_a_refused_request_is_a_definitive_failure_that_created_nothing(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, revision = ready_to_publish(tmp_path)
    submitter_of(dispatcher).outcomes.append(
        BlogSubmissionFailure("provider_rejected", "Blog 暂时无法提交，请稍后重试。", "400")
    )
    started = publish(client, headers, task_id=task_id, revision_id=revision["id"])

    dispatcher.run_all()

    payload = client.get(
        f"/publication/publish-tasks/{started.json()['id']}", headers=headers
    ).json()
    assert payload["status"] == "failed"
    assert payload["preview_url"] is None
    assert payload["failure_message"] == "Blog 暂时无法提交，请稍后重试。"


def test_a_created_response_without_a_confirmed_preview_is_never_a_failure_to_resend(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, revision = ready_to_publish(tmp_path)
    submitter_of(dispatcher).outcomes.append(BlogOutcomeUnknown("no previewPath"))
    started = publish(client, headers, task_id=task_id, revision_id=revision["id"])

    dispatcher.run_all()

    payload = client.get(
        f"/publication/publish-tasks/{started.json()['id']}", headers=headers
    ).json()
    assert payload["status"] == "outcome_unknown"
    assert payload["preview_url"] is None


def test_an_unexpected_fault_never_leaves_a_publication_waiting_forever(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, revision = ready_to_publish(tmp_path)
    submitter_of(dispatcher).outcomes.append(RuntimeError("The adapter broke."))
    started = publish(client, headers, task_id=task_id, revision_id=revision["id"])

    dispatcher.run_all()

    payload = client.get(
        f"/publication/publish-tasks/{started.json()['id']}", headers=headers
    ).json()
    assert payload["status"] == "outcome_unknown"
    assert payload["preview_url"] is None


def test_publication_leaves_the_task_open_for_continued_work(tmp_path: Path) -> None:
    client, headers, dispatcher, task_id, revision = ready_to_publish(tmp_path)
    publish(client, headers, task_id=task_id, revision_id=revision["id"])
    dispatcher.run_all()

    article = client.get(f"/tasks/{task_id}/liyan", headers=headers)

    assert article.status_code == 200, article.text
    assert article.json()["capabilities"]["can_save"] is True
    assert article.json()["revisions"]["current"]["id"] == revision["id"]
    assert client.get("/tasks", headers=headers).json()["items"][0]["id"] == task_id


def test_one_user_cannot_read_or_publish_another_users_article(tmp_path: Path) -> None:
    client, headers, dispatcher, task_id, revision = ready_to_publish(tmp_path)
    started = publish(client, headers, task_id=task_id, revision_id=revision["id"])
    intruder = {"Authorization": "Bearer second-token"}

    assert (
        client.get(
            f"/publication/publish-tasks/{started.json()['id']}", headers=intruder
        ).status_code
        == 404
    )
    assert (
        publish(
            client,
            intruder,
            task_id=task_id,
            revision_id=revision["id"],
            target_key="lsforum-cn",
            key="publish-intruder",
        ).status_code
        == 404
    )


def test_repeating_one_confirmation_returns_the_same_publication_task(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, revision = ready_to_publish(tmp_path)

    first = publish(client, headers, task_id=task_id, revision_id=revision["id"])
    second = publish(client, headers, task_id=task_id, revision_id=revision["id"])

    assert second.status_code == 202, second.text
    assert second.json()["id"] == first.json()["id"]
    assert len(dispatcher.execution_ids) == 1


def test_a_preview_path_that_does_not_belong_to_the_target_site_is_never_shown(
    tmp_path: Path,
) -> None:
    import pytest

    from liyan_server.publication.blog import BlogPreviewSubmission, accept_preview_response

    submission = BlogPreviewSubmission(
        api_base_url="https://blog.lsforum.org",
        token="ingest-secret",
        site_url=SITE_URL,
        title="标题",
        body_markdown="正文",
        author="Zeng Zong",
    )

    with pytest.raises(BlogOutcomeUnknown):
        accept_preview_response(submission, 201, accepted("https://evil.example/preview/abc"))


def test_an_accepted_preview_keeps_the_response_the_platform_actually_returned() -> None:
    payload = accepted()

    result = BlogPreviewAccepted.of(payload)

    assert result.preview_path == "/preview/four-day-week-abc123"
    assert result.slug == "four-day-week"
    assert result.version == "1"
    assert result.response == payload


def test_a_publication_that_could_not_be_queued_does_not_wait_forever(
    tmp_path: Path,
) -> None:
    client, headers, dispatcher, task_id, revision = ready_to_publish(tmp_path)

    def refuse(execution_id: object) -> None:
        raise RuntimeError("The broker is unreachable.")

    dispatcher.dispatch = refuse  # type: ignore[method-assign]
    started = publish(client, headers, task_id=task_id, revision_id=revision["id"])

    assert started.status_code == 202, started.text
    assert started.json()["status"] == "failed"
    assert started.json()["failure_message"] == "发布未能启动，请稍后重试。"
    assert started.json()["preview_url"] is None
