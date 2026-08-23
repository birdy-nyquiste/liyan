"""The LSForum Blog v0.11 Preview adapter.

The MVP uses one upload-only endpoint and sends only what the contract requires:
the locked title, the canonical Markdown body, the target's author, an explicit
`opinion` post type, and `preview` status. A `201` is a success only when the
response itself confirms a Preview, because 立言阁's terminal successful outcome
is a Preview URL a user can open — not the platform's acknowledgement.

Two failure kinds are distinct by design. `BlogSubmissionFailure` means the
attempt definitively did not create anything; `BlogOutcomeUnknown` means Blog
may hold something 立言阁 cannot see, which ADR-0001 makes terminal because
v0.11 offers neither an idempotency key nor a Preview lookup.

Only an answer that proves nothing was written may be called definitive. A
`201` whose body does not confirm a Preview is not one of those: Blog said it
created something, so the outcome is unknown rather than retryable — the exact
case CONTEXT.md names 结果未知.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, Self

import httpx

POST_TYPE = "opinion"
PREVIEW_STATUS = "preview"
POSTS_PATH = "/api/v1/posts"

UNAVAILABLE_MESSAGE = "Blog 暂时无法提交，请稍后重试。"
UNCONFIGURED_MESSAGE = "发布目标尚未配置凭据，请联系管理员。"
UNKNOWN_OUTCOME_MESSAGE = "本次提交结果未知，立言阁不会重发；请到 Blog 查看后再决定。"


@dataclass(frozen=True)
class BlogPreviewSubmission:
    """Everything one attempt sends, resolved from an immutable snapshot."""

    api_base_url: str
    token: str
    site_url: str
    title: str
    body_markdown: str
    author: str


class BlogSubmissionFailure(Exception):
    """A definitive outcome: nothing was created and the snapshot may be resent."""

    def __init__(self, code: str, message: str, internal_error: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.internal_error = internal_error


class BlogOutcomeUnknown(Exception):
    """Blog may hold something this attempt cannot confirm, so never resend."""

    def __init__(self, internal_error: str = "") -> None:
        super().__init__(UNKNOWN_OUTCOME_MESSAGE)
        self.message = UNKNOWN_OUTCOME_MESSAGE
        self.internal_error = internal_error


@dataclass(frozen=True)
class BlogPreviewAccepted:
    preview_path: str
    slug: str | None
    version: str | None
    response: dict[str, object]

    @classmethod
    def of(cls, payload: dict[str, object]) -> Self:
        return cls(
            preview_path=str(payload["previewPath"]),
            slug=_text(payload.get("slug")),
            version=_text(payload.get("version")),
            response=payload,
        )

    def preview_url(self, site_url: str) -> str:
        if self.preview_path.startswith(("http://", "https://")):
            return self.preview_path
        return f"{site_url.rstrip('/')}/{self.preview_path.lstrip('/')}"


class BlogPreviewSubmitter(Protocol):
    def submit(self, submission: BlogPreviewSubmission) -> BlogPreviewAccepted: ...


def submission_url(submission: BlogPreviewSubmission) -> str:
    return f"{submission.api_base_url.rstrip('/')}{POSTS_PATH}"


def submission_body(submission: BlogPreviewSubmission) -> dict[str, object]:
    """The minimal v0.11 payload; optional Blog metadata stays out of the MVP."""
    return {
        "title": submission.title,
        "content": submission.body_markdown,
        "author": submission.author,
        "postType": POST_TYPE,
        "status": PREVIEW_STATUS,
    }


def accept_preview_response(
    submission: BlogPreviewSubmission, status_code: int, payload: object
) -> BlogPreviewAccepted:
    """Turn one Blog answer into a confirmed Preview, a refusal, or 结果未知."""
    if 400 <= status_code < 500:
        # Blog refused the request outright, so nothing was written.
        raise BlogSubmissionFailure(
            "provider_rejected", UNAVAILABLE_MESSAGE, f"Blog responded {status_code}."
        )
    if status_code != 201:
        raise BlogOutcomeUnknown(f"Blog responded {status_code}.")
    if not isinstance(payload, dict):
        raise BlogOutcomeUnknown("Blog created something and returned a non-object.")
    if payload.get("status") != PREVIEW_STATUS:
        raise BlogOutcomeUnknown(
            f"Blog created something and reported status {payload.get('status')!r}."
        )
    preview_path = payload.get("previewPath")
    if not isinstance(preview_path, str) or not preview_path.strip():
        raise BlogOutcomeUnknown("Blog created something and returned no previewPath.")
    if preview_path.startswith(("http://", "https://")) and not preview_path.startswith(
        f"{submission.site_url.rstrip('/')}/"
    ):
        raise BlogOutcomeUnknown(
            "Blog created something and returned a preview path outside the target site."
        )
    return BlogPreviewAccepted.of(payload)


@dataclass(frozen=True)
class BlogHttpResponse:
    status_code: int
    payload: object


type PostResponses = Callable[[str, dict[str, str], dict[str, object]], BlogHttpResponse]


class LsforumBlogSubmitter:
    def __init__(self, *, timeout_seconds: int = 60, post: PostResponses | None = None) -> None:
        self._timeout_seconds = timeout_seconds
        self._post = post or self._post_with_httpx

    def submit(self, submission: BlogPreviewSubmission) -> BlogPreviewAccepted:
        if not submission.token:
            raise BlogSubmissionFailure(
                "target_unconfigured",
                UNCONFIGURED_MESSAGE,
                "No Blog ingest credential is configured.",
            )
        try:
            response = self._post(
                submission_url(submission),
                {
                    "Authorization": f"Bearer {submission.token}",
                    "Content-Type": "application/json",
                },
                submission_body(submission),
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.InvalidURL) as error:
            # Nothing left this process, so the same snapshot may be sent again.
            raise BlogSubmissionFailure(
                "provider_unreachable", UNAVAILABLE_MESSAGE, repr(error)
            ) from error
        except httpx.HTTPError as error:
            # The request was already on the wire; a resend could duplicate a Preview.
            raise BlogOutcomeUnknown(repr(error)) from error
        return accept_preview_response(submission, response.status_code, response.payload)

    def _post_with_httpx(
        self, url: str, headers: dict[str, str], body: dict[str, object]
    ) -> BlogHttpResponse:
        response = httpx.post(url, headers=headers, json=body, timeout=self._timeout_seconds)
        try:
            payload: object = response.json()
        except ValueError:
            payload = None
        return BlogHttpResponse(response.status_code, payload)


def _text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
