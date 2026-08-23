"""The Blog adapter's real HTTP path, driven over a socket.

Every other adapter test injects `post`, which is exactly the seam that hides
whether the request is actually built and sent correctly. These tests run one
throwaway HTTP server on localhost so the bytes, headers, and JSON decoding are
the real ones. LSForum is never contacted.
"""

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from blog_support import accepted

from liyan_server.publication.blog import (
    BlogOutcomeUnknown,
    BlogPreviewSubmission,
    LsforumBlogSubmitter,
)

received: dict[str, Any] = {}


class _Handler(BaseHTTPRequestHandler):
    status_code = 201
    body: bytes = json.dumps(accepted()).encode()

    def do_POST(self) -> None:  # noqa: N802 - the stdlib spells it this way
        length = int(self.headers.get("Content-Length", "0"))
        received.clear()
        received.update(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "content_type": self.headers.get("Content-Type"),
                "body": json.loads(self.rfile.read(length).decode()),
            }
        )
        self.send_response(type(self).status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(type(self).body)))
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, *_: object) -> None:
        """Keep the test output free of one access-log line per request."""


@pytest.fixture
def blog_server() -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _submission(base_url: str) -> BlogPreviewSubmission:
    return BlogPreviewSubmission(
        api_base_url=base_url,
        token="ingest-secret",
        site_url="https://blog.lsforum.org",
        title="四天工作制的真问题",
        body_markdown="工时只是生产方式的一部分。\n\n## 现实条件\n\n改变流程比压缩时间更重要。",
        author="Zeng Zong",
    )


def test_a_real_request_carries_the_bearer_token_and_the_minimal_json_body(
    blog_server: str,
) -> None:
    _Handler.status_code = 201
    _Handler.body = json.dumps(accepted()).encode()

    result = LsforumBlogSubmitter().submit(_submission(blog_server))

    assert received["path"] == "/api/v1/posts"
    assert received["authorization"] == "Bearer ingest-secret"
    assert received["content_type"] == "application/json"
    assert received["body"] == {
        "title": "四天工作制的真问题",
        "content": "工时只是生产方式的一部分。\n\n## 现实条件\n\n改变流程比压缩时间更重要。",
        "author": {"name": "Zeng Zong"},
        "postType": "opinion",
        "status": "preview",
    }
    assert result.preview_url("https://blog.lsforum.org") == (
        "https://blog.lsforum.org/preview/four-day-week-abc123"
    )


def test_a_created_response_that_is_not_json_leaves_the_outcome_unknown(
    blog_server: str,
) -> None:
    _Handler.status_code = 201
    _Handler.body = b"<html>Created</html>"

    with pytest.raises(BlogOutcomeUnknown):
        LsforumBlogSubmitter().submit(_submission(blog_server))


def test_nothing_reaches_a_port_that_refuses_the_connection() -> None:
    from liyan_server.publication.blog import BlogSubmissionFailure

    # Port 1 on loopback refuses immediately, so the request never left.
    with pytest.raises(BlogSubmissionFailure) as failure:
        LsforumBlogSubmitter(timeout_seconds=5).submit(_submission("http://127.0.0.1:1"))

    assert failure.value.code == "provider_unreachable"
