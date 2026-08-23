"""A deterministic stand-in for LSForum Blog.

Kept apart from the other helpers so the shared 知言 dispatcher can hold one
without importing the publication helpers that import it back.
"""

from typing import Any

from liyan_server.publication.blog import BlogPreviewAccepted, BlogPreviewSubmission

SITE_URL = "https://blog.lsforum.org"


def accepted(preview_path: str = "/preview/four-day-week-abc123") -> dict[str, Any]:
    return {
        "status": "preview",
        "previewPath": preview_path,
        "slug": "four-day-week",
        "version": 1,
    }


class DeterministicBlogSubmitter:
    """Answers each submission from a queue of outcomes, defaulting to a Preview."""

    def __init__(self) -> None:
        self.outcomes: list[BlogPreviewAccepted | Exception] = []
        self.submissions: list[BlogPreviewSubmission] = []

    def submit(self, submission: BlogPreviewSubmission) -> BlogPreviewAccepted:
        self.submissions.append(submission)
        outcome = self.outcomes.pop(0) if self.outcomes else BlogPreviewAccepted.of(accepted())
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
