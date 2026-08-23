"""Contract tests for the LSForum Blog v0.11 Preview adapter.

Nothing here opens a socket: the HTTP call is injected, so the request the MVP
promises to send and the answers it is willing to call a success are both
assertable without the platform.
"""

import httpx
import pytest
from blog_support import SITE_URL, accepted

from liyan_server.publication.blog import (
    BlogHttpResponse,
    BlogOutcomeUnknown,
    BlogPreviewSubmission,
    BlogSubmissionFailure,
    LsforumBlogSubmitter,
)

SUBMISSION = BlogPreviewSubmission(
    api_base_url=SITE_URL,
    token="ingest-secret",
    site_url=SITE_URL,
    title="四天工作制的真问题",
    body_markdown="工时只是生产方式的一部分。",
    author="Zeng Zong",
)


type RecordedCall = tuple[str, dict[str, str], dict[str, object]]


def _submitter(
    response: BlogHttpResponse | Exception, recorder: list[RecordedCall]
) -> LsforumBlogSubmitter:
    def post(
        url: str, headers: dict[str, str], body: dict[str, object]
    ) -> BlogHttpResponse:
        recorder.append((url, headers, body))
        if isinstance(response, Exception):
            raise response
        return response

    return LsforumBlogSubmitter(post=post)


def test_the_upload_only_endpoint_receives_the_bearer_credential_and_the_minimal_body() -> None:
    calls: list[RecordedCall] = []

    _submitter(BlogHttpResponse(201, accepted()), calls).submit(SUBMISSION)

    url, headers, body = calls[0]
    assert url == "https://blog.lsforum.org/api/v1/posts"
    assert headers["Authorization"] == "Bearer ingest-secret"
    assert body == {
        "title": "四天工作制的真问题",
        "content": "工时只是生产方式的一部分。",
        "author": {"name": "Zeng Zong"},
        "postType": "opinion",
        "status": "preview",
    }


def test_a_confirmed_preview_response_yields_an_absolute_preview_url() -> None:
    result = _submitter(BlogHttpResponse(201, accepted()), []).submit(SUBMISSION)

    assert result.preview_url(SITE_URL) == f"{SITE_URL}/preview/four-day-week-abc123"
    assert result.slug == "four-day-week"
    assert result.version == "1"


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "draft", "previewPath": "/preview/abc"},
        {"status": "preview"},
        {"status": "preview", "previewPath": "   "},
        {"status": "preview", "previewPath": "https://evil.example/preview/abc"},
        None,
    ],
)
def test_a_201_that_does_not_confirm_a_preview_leaves_the_outcome_unknown(
    payload: object,
) -> None:
    # Blog said it created something. Calling that a retryable failure is the
    # duplicate-Preview risk ADR-0001 refuses.
    with pytest.raises(BlogOutcomeUnknown):
        _submitter(BlogHttpResponse(201, payload), []).submit(SUBMISSION)


@pytest.mark.parametrize("status_code", [400, 401, 409, 422])
def test_a_refusal_is_definitive_because_nothing_was_written(status_code: int) -> None:
    with pytest.raises(BlogSubmissionFailure) as failure:
        _submitter(BlogHttpResponse(status_code, {}), []).submit(SUBMISSION)

    assert failure.value.code == "provider_rejected"


@pytest.mark.parametrize("status_code", [200, 500, 502, 504])
def test_any_other_answer_could_have_written_a_post_and_stays_unknown(
    status_code: int,
) -> None:
    with pytest.raises(BlogOutcomeUnknown):
        _submitter(BlogHttpResponse(status_code, {}), []).submit(SUBMISSION)


def test_a_missing_credential_fails_before_anything_is_sent() -> None:
    calls: list[RecordedCall] = []

    with pytest.raises(BlogSubmissionFailure) as failure:
        _submitter(BlogHttpResponse(201, accepted()), calls).submit(
            BlogPreviewSubmission(**{**SUBMISSION.__dict__, "token": ""})
        )

    assert failure.value.code == "target_unconfigured"
    assert calls == []


def test_a_connection_that_never_opened_stays_definitively_failed() -> None:
    with pytest.raises(BlogSubmissionFailure) as failure:
        _submitter(httpx.ConnectError("refused"), []).submit(SUBMISSION)

    assert failure.value.code == "provider_unreachable"


def test_a_request_already_on_the_wire_without_an_answer_is_never_definitive() -> None:
    with pytest.raises(BlogOutcomeUnknown):
        _submitter(httpx.ReadTimeout("no answer"), []).submit(SUBMISSION)
