"""One real Preview on a real Blog, created on purpose and never undone.

The deterministic adapter tests decide what 立言阁 does with each answer Blog can
give. What they cannot tell you is whether the ingest credential works, whether
the target's `api_base_url` is right, and whether v0.11 still answers a `201`
with the `previewPath` this adapter insists on before it will call a submission
successful. Those are the failures that reach a user as 结果未知 — the outcome
that cannot be retried.

Opt-in, and alone among the live checks it cannot clean up after itself:

    LIYAN_LIVE_BLOG=1 .venv/bin/python -m pytest \\
        apps/server/tests/test_blog_live_contract.py

Every run leaves a password-protected draft on the configured Blog. 立言阁 cannot
retract one and v0.11 offers no lookup to find it again (ADR-0001), so the only
protection is where it is pointed. Point it at a Blog that does not matter.

The draft is a Preview, never a public post: `status` is `preview` and this
adapter has no code path that sends anything else. Whether a Preview is ever
made public is the user's decision in Blog, and outside 立言阁 entirely.
"""

import os
from datetime import UTC, datetime

import pytest

from liyan_server.publication.blog import (
    PREVIEW_STATUS,
    BlogPreviewSubmission,
    LsforumBlogSubmitter,
    submission_body,
)
from liyan_server.publication.targets import configured_targets
from liyan_server.settings import Settings

pytestmark = pytest.mark.skipif(
    os.environ.get("LIYAN_LIVE_BLOG") != "1",
    reason="Set LIYAN_LIVE_BLOG=1 to create a real Preview on the configured Blog.",
)

MARKER = "立言阁发布通道校验"


@pytest.fixture
def submission() -> BlogPreviewSubmission:
    """The snapshot one attempt sends, built from real configuration.

    Titled and dated so that whoever finds it in Blog later knows what made it
    and can delete it without having to ask.
    """
    settings = Settings()
    targets = configured_targets(settings)
    assert targets, "LIYAN_LIVE_BLOG is set but LIYAN_PUBLICATION_TARGETS is empty."
    assert settings.blog_ingest_token, "LIYAN_BLOG_INGEST_TOKEN is empty."
    target = targets[0]
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    return BlogPreviewSubmission(
        api_base_url=target.api_base_url,
        token=settings.blog_ingest_token,
        site_url=target.site_url,
        title=f"{MARKER} {stamp}",
        body_markdown=(
            f"这是 立言阁 发布通道的一次校验，生成于 {stamp}。\n\n"
            "它由自动检查创建，不是文章，可以直接删除。\n"
        ),
        author="立言阁",
    )


def test_a_real_submission_comes_back_as_a_confirmed_preview(
    submission: BlogPreviewSubmission,
) -> None:
    accepted = LsforumBlogSubmitter(timeout_seconds=Settings().blog_timeout_seconds).submit(
        submission
    )

    assert accepted.preview_path, "Blog created something and named no Preview."
    preview_url = accepted.preview_url(submission.site_url)
    assert preview_url.startswith(submission.site_url)
    # Printed rather than only asserted: this is the one check that leaves
    # something behind, and the URL is how somebody goes and looks at it.
    print(f"\nBlog Preview created: {preview_url}")


def test_the_request_asks_for_a_preview_and_never_a_public_post(
    submission: BlogPreviewSubmission,
) -> None:
    """Nothing 立言阁 sends can publish. Checked here against the real payload.

    Deterministic elsewhere too, and repeated at the live gate because this is
    the assertion that would matter most if it were ever wrong: the difference
    between a draft only the user can reach and something the whole internet can.
    """
    body = submission_body(submission)

    assert body["status"] == PREVIEW_STATUS
    assert "publish" not in {str(value).lower() for value in body.values()}
